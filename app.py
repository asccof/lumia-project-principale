# app.py — version unifiée et propre pour Tighri

from __future__ import annotations
import os, io, uuid, secrets, hashlib, requests
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from typing import Optional

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response, current_app, make_response, g, abort
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from authlib.integrations.flask_client import OAuth
from sqlalchemy import or_, text
# --- Helpers robustes pour récupérer/créer le profil pro sans casser le modèle ---

# --- Helpers robustes pour récupérer/créer le profil pro sans casser le modèle ---

def _query_professional_for_user(db, Professional, User, current_user):
    """
    Retourne une requête SQLAlchemy pour trouver le Professional du current_user,
    en s'adaptant au schéma actuel.
    Ordre de préférence:
      1) name == current_user.username (schéma actuel)
      2) colonne user_id (si jamais elle apparaît un jour)
      3) relation user (si jamais elle apparaît un jour)
      4) fallback très conservateur (jointure par id) -> évité si possible
    """
    # cas 0 : schéma actuel — on associe par le nom d'utilisateur
    if hasattr(Professional, "name") and getattr(current_user, "username", None):
        return Professional.query.filter_by(name=current_user.username)

    # cas 1 : colonne user_id présente
    if hasattr(Professional, "user_id"):
        return Professional.query.filter_by(user_id=current_user.id)

    # cas 2 : relation 'user' présente (définie via db.relationship)
    if hasattr(Professional, "user"):
        return Professional.query.filter_by(user=current_user)

    # cas 3 : dernier recours (à éviter) — jointure id=id
    try:
        return db.session.query(Professional).join(User, User.id == Professional.id).filter(User.id == current_user.id)
    except Exception:
        # Requête \"vide\" inoffensive si tout échoue
        return Professional.query.filter(False)


def get_or_create_professional_for_current_user(db, Professional, User, current_user, defaults=None):
    """
    Récupère le Professional du current_user; si absent, le crée proprement
    sans supposer de schéma précis.
    """
    defaults = defaults or {}
    q = _query_professional_for_user(db, Professional, User, current_user)
    professional = q.first()

    if professional:
        return professional

    # Création non-destructive alignée avec ton schéma actuel
    professional = Professional()

    # Priorité: lier par le nom d'utilisateur (schéma actuel)
    if hasattr(Professional, "name") and getattr(current_user, "username", None):
        try:
            professional.name = current_user.username
        except Exception:
            pass

    # Compat: si jamais user_id/relation existent dans un futur schéma
    if hasattr(Professional, "user_id"):
        try:
            setattr(professional, "user_id", current_user.id)
        except Exception:
            pass
    if hasattr(Professional, "user"):
        try:
            setattr(professional, "user", current_user)
        except Exception:
            pass

    # Pré-remplissages doux (uniquement si les champs existent)
    base_defaults = {
        "description": "Profil en cours de complétion.",
        "availability": "disponible",
        "consultation_types": "cabinet",
        "status": "en_attente",
    }
    base_defaults.update(defaults or {})
    for key, val in base_defaults.items():
        if hasattr(Professional, key) and getattr(professional, key, None) in (None, ""):
            try:
                setattr(professional, key, val)
            except Exception:
                pass

    # Optionnel: si le modèle a `phone` et que l'utilisateur en a un
    if hasattr(Professional, "phone") and getattr(current_user, "phone", None) and not getattr(professional, "phone", None):
        try:
            professional.phone = current_user.phone
        except Exception:
            pass

    db.session.add(professional)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return professional


# ========== PIL (images) ==========
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# ========== Notifications sûres ==========
from notifications import send_email as _notif_send_email
def safe_send_email(to_addr: str, subject: str, body_text: str, html: str | None = None) -> bool:
    try:
        if not to_addr:
            current_app.logger.warning("[EMAIL] destinataire manquant")
            return False
        ok = _notif_send_email(to_addr, subject, body_text, html)
        (current_app.logger.info if ok else current_app.logger.error)(
            "[EMAIL] %s -> %s : %s", "envoyé" if ok else "échec", to_addr, subject
        )
        return ok
    except Exception as e:
        current_app.logger.exception("safe_send_email exception: %s", e)
        return False

# ========== Constantes ==========
BASE_DIR = Path(__file__).resolve().parent
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = UPLOAD_ROOT / "profiles"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif"}
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo

DEFAULT_LANG = os.getenv("DEFAULT_LANG", "fr")
SUPPORTED_LANGS = {"fr", "ar", "en"}
LANG_COOKIE = "lang"

# ========== App ==========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["REMEMBER_COOKIE_NAME"] = "tighri_remember"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=60)
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Créer dossiers d’upload si besoin
try:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)

# ========== DB & modèles ==========
def _normalize_pg_uri(uri: str) -> str:
    if not uri:
        return uri
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    # forcer driver psycopg3
    if uri.startswith("postgresql+psycopg2://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    # sslmode=require si absent
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)
    if parsed.scheme.startswith("postgresql+psycopg") and "sslmode" not in q:
        q["sslmode"] = ["require"]
        uri = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return uri

# On utilise le db des models (source de vérité)
from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot
uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL") or ""
if not uri:
    raise RuntimeError("DATABASE_URL manquant : lie ta base Postgres dans Render.")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_pg_uri(uri)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db.init_app(app)

# ========== Admin (Blueprint) ==========
from admin_server import admin_bp, ProfessionalOrder, _build_notif
app.register_blueprint(admin_bp, url_prefix="/admin")

# ========== Login Manager ==========
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def _load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None
@app.after_request
def _vary_on_cookie_for_lang(resp):
    # N'applique qu'aux pages HTML (laisse les images/CSS/JS tranquilles)
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        # Indique aux caches/CDN que le contenu varie selon les cookies (ici: lang)
        existing_vary = resp.headers.get("Vary")
        resp.headers["Vary"] = "Cookie" if not existing_vary else f"{existing_vary}, Cookie"
        # Empêche la mise en cache partagée (CDN/Proxy). Le navigateur peut garder un court cache privé si tu veux.
        resp.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
    return resp

# ========== OAuth Google ==========
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v3/",
    client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
)

# ========== Langue (compatible base.html) ==========
# --- MICRO I18N (drop-in) ----------------------------------------------------
# Dictionnaires minimalistes pour base + index
TRANSLATIONS = {
    "fr": {
        # Nav
        "nav.home": "Accueil",
        "nav.professionals": "Professionnels",
        "nav.anthecc": "ANTHECC",
        "nav.about": "À propos",
        "nav.contact": "Contact",
        "nav.status": "Statut",

        # Auth
        "auth.login": "Connexion",
        "auth.register": "Inscription",
        "auth.logout": "Déconnexion",
        "auth.profile": "Profil",
        "auth.orders": "Commandes",

        # Index / Hero
        "home.tagline": "La plateforme marocaine pour prendre rendez-vous avec des psychologues, thérapeutes et coachs certifiés",

        # Search
        "search.q.placeholder": "Nom, mot-clé...",
        "search.city.placeholder": "Ville",
        "search.specialty.placeholder": "Spécialité",
        "search.mode.label": "Mode",
        "search.mode.cabinet": "Cabinet",
        "search.mode.visio": "Visio",
        "search.mode.domicile": "Domicile",
        "search.submit": "Rechercher",

        # Sections (2 blocs)
        "sections.patient.title": "Espace Patient",
        "sections.patient.desc": "Consultez les profils, prenez rendez-vous en cabinet, à domicile ou en vidéo avec des professionnels certifiés.",
        "sections.patient.cta": "Je suis patient",
        "sections.pro.title": "Espace Professionnel",
        "sections.pro.desc": "Rejoignez Tighri pour proposer vos services et gérer vos rendez-vous en toute simplicité.",
        "sections.pro.cta": "Je suis professionnel",

        # Grids
        "featured.title": "Professionnels en vedette",
        "card.view_profile": "Voir le profil",
        "other.title": "Autres professionnels",
        "other.view": "Voir",

        # About
        "about.title": "À propos de Tighri",
        "about.p1": "Tighri est la première plateforme marocaine dédiée à la santé mentale et au bien-être. Nous connectons patients et professionnels pour faciliter l'accès à des soins psychologiques de qualité.",
        "about.p2": "Notre mission est de démocratiser l'accès aux services de santé mentale au Maroc, dans un environnement de confiance et de sécurité.",

        # Services
        "services.title": "Nos Services",
        "services.cabinet.title": "Consultations en Cabinet",
        "services.cabinet.desc": "Rencontrez des professionnels en face à face.",
        "services.home.title": "Consultations à Domicile",
        "services.home.desc": "Certains professionnels se déplacent chez vous.",
        "services.video.title": "Consultations en Vidéo",
        "services.video.desc": "Consultez en ligne en toute sécurité.",
        "services.schedule.title": "Gestion de Planning",
        "services.schedule.desc": "Réservez vos créneaux, rappel 24h avant.",
        "services.verified.title": "Profils Vérifiés",
        "services.verified.desc": "Diplômes et identités vérifiés par Tighri.",
        "services.support.title": "Support 24/7",
        "services.support.desc": "Nous vous accompagnons à chaque étape.",

        # Contact
        "contact.title": "Nous contacter",
        "contact.lead": "Bienvenue au Centre d'écoute et de conseil Tighri. Besoin d'aide ou de conseils gratuits ? Contactez-nous.",
        "contact.email": "Email",
        "contact.phone": "Téléphone",
        "contact.whatsapp": "WhatsApp",
        "contact.btn.email": "✉️ Contacter par e-mail",
        "contact.btn.phone": "📞 Appeler le {phone}",
        "contact.btn.whatsapp": "💬 WhatsApp direct",
    },
    "en": {
        "nav.home": "Home",
        "nav.professionals": "Professionals",
        "nav.anthecc": "ANTHECC",
        "nav.about": "About",
        "nav.contact": "Contact",
        "nav.status": "Status",

        "auth.login": "Log in",
        "auth.register": "Sign up",
        "auth.logout": "Log out",
        "auth.profile": "Profile",
        "auth.orders": "Orders",

        "home.tagline": "Morocco’s platform to book appointments with certified psychologists, therapists, and coaches",

        "search.q.placeholder": "Name, keyword...",
        "search.city.placeholder": "City",
        "search.specialty.placeholder": "Specialty",
        "search.mode.label": "Mode",
        "search.mode.cabinet": "In office",
        "search.mode.visio": "Video",
        "search.mode.domicile": "Home visit",
        "search.submit": "Search",

        "sections.patient.title": "Patient Space",
        "sections.patient.desc": "Browse profiles and book appointments in office, at home, or by video with certified professionals.",
        "sections.patient.cta": "I’m a patient",
        "sections.pro.title": "Professional Space",
        "sections.pro.desc": "Join Tighri to offer your services and manage your appointments with ease.",
        "sections.pro.cta": "I’m a professional",

        "featured.title": "Featured professionals",
        "card.view_profile": "View profile",
        "other.title": "Other professionals",
        "other.view": "View",

        "about.title": "About Tighri",
        "about.p1": "Tighri is Morocco’s first platform dedicated to mental health and well-being, connecting patients and professionals to ease access to quality care.",
        "about.p2": "Our mission is to democratize access to mental health services in Morocco in a trusted and safe environment.",

        "services.title": "Our Services",
        "services.cabinet.title": "In-office Consultations",
        "services.cabinet.desc": "Meet professionals face to face.",
        "services.home.title": "Home Consultations",
        "services.home.desc": "Some professionals can come to you.",
        "services.video.title": "Video Consultations",
        "services.video.desc": "Consult online securely.",
        "services.schedule.title": "Scheduling",
        "services.schedule.desc": "Book slots and get a reminder 24h before.",
        "services.verified.title": "Verified Profiles",
        "services.verified.desc": "Degrees and identities verified by Tighri.",
        "services.support.title": "24/7 Support",
        "services.support.desc": "We support you at every step.",

        "contact.title": "Contact us",
        "contact.lead": "Welcome to Tighri’s listening and counseling center. Need help or free advice? Get in touch.",
        "contact.email": "Email",
        "contact.phone": "Phone",
        "contact.whatsapp": "WhatsApp",
        "contact.btn.email": "✉️ Contact by email",
        "contact.btn.phone": "📞 Call {phone}",
        "contact.btn.whatsapp": "💬 WhatsApp",
    },
    "ar": {
        "nav.home": "الرئيسية",
        "nav.professionals": "الاختصاصيون",
        "nav.anthecc": "ANTHECC",
        "nav.about": "من نحن",
        "nav.contact": "اتصل بنا",
        "nav.status": "حالة الموقع",

        "auth.login": "تسجيل الدخول",
        "auth.register": "إنشاء حساب",
        "auth.logout": "تسجيل الخروج",
        "auth.profile": "الملف الشخصي",
        "auth.orders": "الطلبات",

        "home.tagline": "المنصة المغربية لحجز مواعيد مع علماء النفس والمعالجين والمدربين المعتمدين",

        "search.q.placeholder": "الاسم أو كلمة مفتاحية...",
        "search.city.placeholder": "المدينة",
        "search.specialty.placeholder": "التخصص",
        "search.mode.label": "الوضع",
        "search.mode.cabinet": "عيادة",
        "search.mode.visio": "مرئي (عن بُعد)",
        "search.mode.domicile": "منزل",
        "search.submit": "بحث",

        "sections.patient.title": "فضاء المرضى",
        "sections.patient.desc": "اطّلع على الملفات واحجز موعداً في العيادة أو المنزل أو عبر الفيديو مع مختصين معتمدين.",
        "sections.patient.cta": "أنا مريض/مراجِع",
        "sections.pro.title": "فضاء المهنيين",
        "sections.pro.desc": "انضم إلى تيغري لعرض خدماتك وإدارة مواعيدك بسهولة.",
        "sections.pro.cta": "أنا مهني",

        "featured.title": "مختصون مميزون",
        "card.view_profile": "عرض الملف",
        "other.title": "مختصون آخرون",
        "other.view": "عرض",

        "about.title": "حول تيغري",
        "about.p1": "تيغري هي أول منصة مغربية مخصصة للصحة النفسية والرفاه. نربط بين المرضى والمهنيين لتسهيل الوصول إلى رعاية نفسية ذات جودة.",
        "about.p2": "مهمتنا هي ديمقراطية الوصول إلى خدمات الصحة النفسية في المغرب في بيئة من الثقة والأمان.",

        "services.title": "خدماتنا",
        "services.cabinet.title": "استشارات في العيادة",
        "services.cabinet.desc": "قابلوا المختصين وجهاً لوجه.",
        "services.home.title": "استشارات منزلية",
        "services.home.desc": "بعض المختصين يزورونكم في المنزل.",
        "services.video.title": "استشارات عبر الفيديو",
        "services.video.desc": "استشر عبر الإنترنت بأمان كامل.",
        "services.schedule.title": "إدارة المواعيد",
        "services.schedule.desc": "احجز مواعيدك وتلقَّ تذكيراً قبل 24 ساعة.",
        "services.verified.title": "ملفات موثّقة",
        "services.verified.desc": "الديبلومات والهويات موثقة من طرف تيغري.",
        "services.support.title": "دعم 24/7",
        "services.support.desc": "نرافقكم في كل خطوة.",

        "contact.title": "اتصل بنا",
        "contact.lead": "مرحباً بكم في مركز الاستماع والإرشاد تيغري. تحتاج مساعدة أو استشارة مجانية؟ تواصل معنا.",
        "contact.email": "البريد الإلكتروني",
        "contact.phone": "الهاتف",
        "contact.whatsapp": "واتساب",
        "contact.btn.email": "✉️ مراسلة عبر البريد",
        "contact.btn.phone": "📞 اتصال {phone}",
        "contact.btn.whatsapp": "💬 واتساب مباشر",
    },
}

def t(key: str, **kwargs) -> str:
    """Petit helper de traduction en Jinja: {{ t('clé') }}"""
    lang = getattr(g, "current_locale", None) or DEFAULT_LANG
    bundle = TRANSLATIONS.get(lang, TRANSLATIONS["fr"])
    s = bundle.get(key, TRANSLATIONS["fr"].get(key, key))
    try:
        return s.format(**kwargs) if kwargs else s
    except Exception:
        return s

# Remplace l'ancien injecteur par celui-ci
@app.context_processor
def inject_lang():
    lang = _normalize_lang(request.cookies.get(LANG_COOKIE))
    label_map = {"fr": "Français", "ar": "العربية", "en": "English"}
    dir_map = {"ar": "rtl", "fr": "ltr", "en": "ltr"}
    return {
        "current_lang": lang,
        "current_lang_label": label_map.get(lang, "Français"),
        "text_dir": dir_map.get(lang, "ltr"),
        "SUPPORTED_LANGS": SUPPORTED_LANGS,
        "t": t,
    }
# --- FIN MICRO I18N ----------------------------------------------------------

# Important pour CDN/Cloudflare: on indique que le HTML varie selon Cookie
@app.after_request
def _vary_on_cookie_for_lang(resp):
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        existing_vary = resp.headers.get("Vary")
        resp.headers["Vary"] = "Cookie" if not existing_vary else f"{existing_vary}, Cookie"
        resp.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
    return resp

@app.context_processor
def inject_lang():
    lang = _normalize_lang(request.cookies.get(LANG_COOKIE))
    return {"current_lang": lang, "SUPPORTED_LANGS": SUPPORTED_LANGS}
# --- LANG SWITCH: durcissement cache + domaine canonique + debug ----
from flask import jsonify

# 1) Domaine canonique (évite que le cookie soit sur .ma et que tu lises sur .com)
PRIMARY_HOST = os.getenv("PRIMARY_HOST", "www.tighri.ma")
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", None)  # ex: ".tighri.ma" (inclut sous-domaines) ou laisse vide

@app.before_request
def _enforce_canonical_host():
    # Si tu utilises plusieurs domaines (ex: .ma et .com), on force vers le primaire
    # => le cookie de langue restera sur un seul domaine.
    host = (request.host or "").split(":")[0]
    if PRIMARY_HOST and host and host != PRIMARY_HOST:
        # garde le schéma + chemin + query, remplace juste l’hôte
        target = request.url.replace(host, PRIMARY_HOST, 1)
        return redirect(target, code=301)

# 2) Set-language (repose le cookie avec domain si fourni)
@app.route('/set-language/<lang>', methods=['GET'], endpoint='set_language_path')
@app.route('/set-language', methods=['GET'], endpoint='set_language_qs')
def set_language(lang: str | None = None):
    lang = _normalize_lang(lang or request.args.get('lang') or request.args.get('lang_code'))
    resp = make_response(redirect(request.referrer or url_for('index')))
    cookie_kwargs = dict(
        key=LANG_COOKIE,
        value=lang,
        max_age=60*60*24*180,
        samesite="Lax",
        secure=True,
        httponly=False,
        path="/",
    )
    if COOKIE_DOMAIN:
        cookie_kwargs["domain"] = COOKIE_DOMAIN
    resp.set_cookie(**cookie_kwargs)
    return resp

# 3) Pas de cache HTML côté proxy (Cloudflare) et on varie sur le cookie
@app.after_request
def _vary_on_cookie_and_no_cache(resp):
    try:
        # Évite que Cloudflare serve la même HTML à tout le monde
        if resp.mimetype and 'text/html' in resp.mimetype:
            # empêche le cache HTML côté proxy/navigateur
            resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            resp.headers['Pragma'] = 'no-cache'
            # indique qu'on varie selon les cookies
            vary = resp.headers.get('Vary', '')
            parts = [p.strip() for p in vary.split(',') if p.strip()]
            if 'Cookie' not in [p.title() for p in parts]:
                parts.append('Cookie')
            if parts:
                resp.headers['Vary'] = ', '.join(parts)
    except Exception:
        pass
    return resp

# 4) DEBUG : vérifie côté serveur que la langue est bien lue
@app.route("/debug/lang")
def debug_lang():
    return jsonify({
        "cookie_lang": request.cookies.get(LANG_COOKIE),
        "g.current_locale": getattr(g, "current_locale", None),
        "label": getattr(g, "current_locale_label", None),
        "host": request.host,
        "primary_host": PRIMARY_HOST,
        "cookie_domain_env": COOKIE_DOMAIN,
    })
# --- FIN BLOC ---


# ========== Helpers images ==========
AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
PLACEHOLDER_AVATAR = os.path.join(app.root_path, "static", "avatar_default.webp")

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _process_and_save_profile_image(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _ext_ok(filename):
        raise ValueError("Extension non autorisée")
    raw = file_storage.read()
    if not _PIL_OK:
        raise RuntimeError("Le traitement d'image nécessite Pillow (PIL).")

    # validation
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # strip EXIF + crop carré 512
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))
    img_square = ImageOps.fit(img_no_exif, (512, 512), Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = UPLOAD_FOLDER / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_name

def _avatar_file_for(pid: int) -> Optional[str]:
    if not os.path.isdir(AVATAR_DIR):
        return None
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        path = os.path.join(AVATAR_DIR, f"{pid}{ext}")
        if os.path.isfile(path):
            return path
    return None

PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

# ========== Routes techniques ==========
@app.route("/favicon.ico")
def favicon():
    fav_path = Path(app.static_folder or (BASE_DIR / "static")) / "favicon.ico"
    if fav_path.exists():
        resp = send_from_directory(app.static_folder, "favicon.ico", conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp
    return ("", 204)

@app.route("/robots.txt")
def robots():
    txt_path = Path(app.static_folder or (BASE_DIR / "static")) / "robots.txt"
    if txt_path.exists():
        return send_from_directory(app.static_folder, "robots.txt", mimetype="text/plain")
    return ("User-agent: *\nDisallow:\n", 200, {"Content-Type": "text/plain"})

# ========== Pages publiques ==========
@app.route("/", endpoint="index")
def index():
    # Tri admin si table d’ordre dispo, sinon fallback
    try:
        base = (
            db.session.query(Professional)
            .outerjoin(ProfessionalOrder, ProfessionalOrder.professional_id == Professional.id)
            .filter(Professional.status == 'valide')
            .order_by(
                db.func.coalesce(ProfessionalOrder.order_priority, 999999).asc(),
                Professional.is_featured.desc(),
                db.func.coalesce(Professional.featured_rank, 999999).asc(),
                Professional.created_at.desc(),
                Professional.id.desc()
            )
        )
        top_professionals = base.limit(9).all()
        top_ids = [p.id for p in top_professionals]
        more_professionals = base.filter(~Professional.id.in_(top_ids)).all() if top_ids else base.offset(9).all()
    except Exception as e:
        app.logger.warning("Classement admin indisponible (%s), fallback 'featured puis récents'.", e)
        fb = (
            Professional.query
            .filter_by(status='valide')
            .order_by(
                Professional.is_featured.desc(),
                db.func.coalesce(Professional.featured_rank, 999999).asc(),
                Professional.created_at.desc(),
                Professional.id.desc()
            )
        )
        top_professionals = fb.limit(9).all()
        top_ids = [p.id for p in top_professionals]
        more_professionals = fb.filter(~Professional.id.in_(top_ids)).all() if top_ids else fb.offset(9).all()

    return render_template("index.html",
        top_professionals=top_professionals,
        more_professionals=more_professionals
    )

@app.route("/anthecc", endpoint="anthecc")
def anthecc():
    tpl = BASE_DIR / "templates" / "anthecc.html"
    return render_template("anthecc.html") if tpl.exists() else ("ANTHECC", 200)

@app.route("/about", endpoint="about")
def about():
    return render_template("about.html")

@app.route("/contact", endpoint="contact")
def contact():
    return render_template("contact.html")

# Listing / recherche
@app.route("/professionals", endpoint="professionals")
def professionals():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    specialty = (request.args.get("specialty") or "").strip()
    mode = (request.args.get("mode") or "").strip().lower()

    qry = Professional.query.filter_by(status='valide')

    if q:
        like = f"%{q}%"
        conds = []
        for attr in ("name", "full_name", "description", "specialty", "location", "address"):
            if hasattr(Professional, attr):
                conds.append(getattr(Professional, attr).ilike(like))
        if conds:
            qry = qry.filter(or_(*conds))

    if city and hasattr(Professional, "location"):
        qry = qry.filter(Professional.location.ilike(f"%{city}%"))

    if specialty:
        like = f"%{specialty}%"
        if hasattr(Professional, "specialty"):
            qry = qry.filter(Professional.specialty.ilike(like))

    if mode and hasattr(Professional, "consultation_types"):
        qry = qry.filter(Professional.consultation_types.ilike(f"%{mode}%"))

    pros = qry.order_by(Professional.is_featured.desc(), Professional.created_at.desc()).all()
    return render_template("professionals.html", professionals=pros, specialty=specialty, search_query=q)

# Fiche pro
@app.route("/professional/<int:professional_id>", endpoint="professional_detail")
def professional_detail(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    return render_template("professional_detail.html", professional=professional)

# ========== Photos / médias ==========
@app.route("/media/profile/<int:professional_id>", endpoint="profile_photo")
def profile_photo(professional_id: int):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

    # Fichiers uploadés localement (/media/profiles/NAME)
    if raw_url.startswith("/media/profiles/"):
        fname = raw_url.split("/media/profiles/")[-1]
        safe_name = os.path.basename(fname)
        fpath = UPLOAD_FOLDER / safe_name
        if fpath.exists():
            resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
            resp.headers["Cache-Control"] = "public, max-age=31536000"
            return resp
        return _avatar_fallback_response()

    if not raw_url:
        # avatars pack statique (ex: static/avatars/ID.webp)
        file_path = _avatar_file_for(professional_id)
        if file_path and os.path.isfile(file_path):
            return send_from_directory(AVATAR_DIR, os.path.basename(file_path), max_age=60*60*24*7)
        if os.path.isfile(PLACEHOLDER_AVATAR):
            return send_from_directory(os.path.join(app.root_path, "static"), "avatar_default.webp", max_age=86400)
        return _avatar_fallback_response()

    # Proxy https
    if raw_url.startswith("http://"):
        raw_url = "https://" + raw_url[len("http://"):]
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        return _avatar_fallback_response()

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TighriBot/1.0; +https://www.tighri.com)",
        "Referer": "https://www.tighri.com",
    }
    try:
        r = requests.get(raw_url, headers=headers, timeout=8, stream=True)
        r.raise_for_status()
    except Exception:
        return _avatar_fallback_response()

    content_type = r.headers.get("Content-Type", "image/jpeg")
    resp = Response(r.content, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

# Alias rétro-compatibles
@app.route("/avatar", endpoint="avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id: int):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# Upload photo pro
@app.route("/professional/profile/photo", methods=["GET", "POST"], endpoint="professional_upload_photo")
@login_required
def professional_upload_photo():
    if current_user.user_type != "professional":
        flash("Accès non autorisé")
        return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("professional_dashboard"))

    if request.method == "POST":
        file = request.files.get("photo")
        if not file:
            flash("Veuillez sélectionner une image.", "warning")
            return redirect(url_for("professional_upload_photo"))
        try:
            saved_name = _process_and_save_profile_image(file)
            pro.image_url = f"/media/profiles/{saved_name}"
            db.session.commit()
            flash("Photo de profil mise à jour avec succès.", "success")
            return redirect(url_for("professional_dashboard"))
        except RuntimeError:
            current_app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            current_app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")

    return render_template("upload_photo.html")

# ========== Auth local ==========
@app.route("/register", methods=["GET","POST"], endpoint="register")
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        phone = (request.form.get("phone") or "").strip()

        if not username or not email or not password or not phone:
            flash("Tous les champs (dont téléphone) sont obligatoires.")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type="patient",
            phone=phone,
        )
        db.session.add(user)
        db.session.commit()
        flash("Compte patient créé avec succès!")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/professional_register", methods=["GET","POST"], endpoint="professional_register")
def professional_register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        specialty = (request.form.get("specialty") or "").strip()
        city = (request.form.get("city") or "").strip()
        description = (request.form.get("description") or "").strip()
        experience_raw = request.form.get("experience", "0")
        fee_raw = request.form.get("consultation_fee", "0")
        phone = (request.form.get("phone") or "").strip()

        facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        instagram_url = (request.form.get('instagram_url') or '').strip() or None
        tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        youtube_url   = (request.form.get('youtube_url')   or '').strip() or None

        if not username or not email or not password or not phone:
            flash("Tous les champs obligatoires (dont téléphone) ne sont pas remplis.")
            return redirect(url_for("professional_register"))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for("professional_register"))
        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré")
            return redirect(url_for("professional_register"))

        try:
            experience = int((experience_raw or "0").strip())
        except ValueError:
            experience = 0
        try:
            consultation_fee = float((fee_raw or "0").replace(",", "."))
        except ValueError:
            consultation_fee = 0.0

        try:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                user_type="professional",
                phone=phone,
            )
            db.session.add(user)

            professional = Professional(
                name=username,
                description=description or "Profil en cours de complétion.",
                specialty=specialty or "Psychologue",
                location=city or "Casablanca",
                experience_years=experience,
                consultation_fee=consultation_fee,
                phone=phone or None,
                availability='disponible',
                consultation_types='cabinet',
                facebook_url=facebook_url,
                instagram_url=instagram_url,
                tiktok_url=tiktok_url,
                youtube_url=youtube_url,
                social_links_approved=False,
                status='en_attente',
            )
            db.session.add(professional)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la création du compte professionnel. Réessayez.", "danger")
            return redirect(url_for("professional_register"))

        flash("Compte professionnel créé avec succès! Un administrateur validera votre profil.")
        return redirect(url_for("login"))

    return render_template("professional_register.html")

@app.route("/login", methods=["GET","POST"], endpoint="login")
def login():
    if request.method == "POST":
        username_or_email = (request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            or_(User.username == username_or_email, User.email == username_or_email.lower())
        ).first()

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember, duration=timedelta(days=60))
            flash("Connexion réussie!")
            return redirect(url_for("professional_dashboard" if user.user_type == "professional" else "index"))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")
    return render_template("login.html")

@app.route("/logout", endpoint="logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

# ========== OAuth Google ==========
@app.route("/auth/google")
def auth_google():
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", url_for("auth_google_callback", _external=True, _scheme="https"))
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google/callback")
def auth_google_callback():
    try:
        token = google.authorize_access_token()
        userinfo = google.get("userinfo").json()
        sub = userinfo.get("sub")
        email = (userinfo.get("email") or "").lower().strip()
        name = userinfo.get("name")
        picture = userinfo.get("picture")

        if not email:
            flash("Impossible de récupérer votre email Google.", "danger")
            return redirect(url_for("login"))

        user = User.query.filter(or_(User.oauth_sub == sub, User.email == email)).first()

        if user:
            changed = False
            if not user.oauth_sub and sub:
                user.oauth_provider = "google"; user.oauth_sub = sub; changed = True
            if picture and not user.picture_url:
                user.picture_url = picture; changed = True
            if name and not user.full_name:
                user.full_name = name; changed = True
            if changed:
                db.session.commit()
        else:
            username_base = email.split("@")[0]
            username = username_base
            i = 1
            while User.query.filter_by(username=username).first():
                username = f"{username_base}{i}"; i += 1

            user = User(
                username=username, email=email,
                oauth_provider="google", oauth_sub=sub,
                full_name=name, picture_url=picture,
                user_type="professional"
            )
            db.session.add(user); db.session.commit()

        login_user(user, remember=True, duration=timedelta(days=60))
        flash("Connexion via Google réussie ✅", "success")
        return redirect(url_for("professional_dashboard" if user.user_type == "professional" else "index"))

    except Exception:
        flash("Connexion Google impossible. Réessayez.", "danger")
        return redirect(url_for("login"))

# ========== Mot de passe : reset ==========
def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()

def issue_reset_token(user, hours=24) -> str:
    tok = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(tok)
    user.reset_token_expires_at = datetime.utcnow() + timedelta(hours=hours)
    db.session.commit()
    return tok

def consume_token_to_user(token: str):
    if not token:
        return None
    h = _hash_token(token)
    u = User.query.filter_by(reset_token_hash=h).first()
    if not u or not u.reset_token_expires_at or u.reset_token_expires_at < datetime.utcnow():
        return None
    return u

@app.route("/change_password", methods=["GET","POST"], endpoint="change_password")
@login_required
def change_password():
    if request.method == "POST":
        old = (request.form.get("old") or "").strip()
        new = (request.form.get("new") or "").strip()
        confirm = (request.form.get("confirm") or "").strip()

        has_local_pw = bool(current_user.password_hash)
        if has_local_pw:
            if not check_password_hash(current_user.password_hash, old):
                flash("Ancien mot de passe incorrect.", "danger")
                return redirect(url_for("change_password"))
            if old and new and old == new:
                flash("Le nouveau mot de passe doit être différent de l'ancien.", "danger")
                return redirect(url_for("change_password"))
        else:
            if old:
                flash("Ce compte n'a pas de mot de passe local.", "warning")
                return redirect(url_for("change_password"))

        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for("change_password"))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for("change_password"))

        current_user.password_hash = generate_password_hash(new)
        db.session.commit()
        flash("Mot de passe modifié.", "success")
        return redirect(url_for("index"))
    return render_template("change_password.html")

@app.route("/forgot_password", methods=["GET","POST"], endpoint="forgot_password")
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        flash("Si le compte existe, un email de réinitialisation a été envoyé.", "info")
        if not email:
            return redirect(url_for("login"))

        user = User.query.filter_by(email=email).first()
        if not user:
            return redirect(url_for("login"))

        try:
            raw_token = issue_reset_token(user, hours=24)
            reset_link = url_for("reset_password", token=raw_token, _external=True, _scheme="https")
            subj = f"{BRAND_NAME} — Réinitialisation du mot de passe"
            txt = (
                f"Bonjour,\n\nVous avez demandé à réinitialiser votre mot de passe {BRAND_NAME}.\n"
                f"Cliquez sur ce lien (valable 24h) : {reset_link}\n\n"
                f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
            )
            html = (
                f"<p>Bonjour,</p><p>Vous avez demandé à réinitialiser votre mot de passe "
                f"<strong>{BRAND_NAME}</strong>.</p>"
                f"<p><a href='{reset_link}'>Réinitialiser mon mot de passe</a> (valable 24&nbsp;heures)</p>"
                f"<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
            )
            safe_send_email(user.email, subj, txt, html)
        except Exception as e:
            current_app.logger.warning("forgot_password: %s", e)
        return redirect(url_for("login"))
    return render_template("forgot_password.html")

@app.route("/reset_password/<token>", methods=["GET","POST"], endpoint="reset_password")
def reset_password(token: str):
    user = consume_token_to_user(token)
    if not user:
        flash("Lien invalide ou expiré. Refaite une demande.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new = (request.form.get("new") or "").strip()
        confirm = (request.form.get("confirm") or "").strip()
        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for("reset_password", token=token))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for("reset_password", token=token))

        user.password_hash = generate_password_hash(new)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        db.session.commit()
        flash("Mot de passe réinitialisé. Vous pouvez vous connecter.", "success")
        return redirect(url_for("login"))
    return render_template("reset_password.html")

# ========== Espace pro / RDV ==========
@app.route("/professional_dashboard", endpoint="professional_dashboard")
@login_required
def professional_dashboard():
    if current_user.user_type != "professional":
        flash("Accès non autorisé")
        return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("index"))
    appointments = Appointment.query.filter_by(professional_id=professional.id)\
        .order_by(Appointment.appointment_date.desc()).all()
    return render_template("professional_dashboard.html",
                           professional=professional, appointments=appointments)

# Dispos hebdo
@app.route("/professional/availability", methods=["GET","POST"], endpoint="professional_availability")
@login_required
def professional_availability():
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))

    if request.method == "POST":
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        def add_window(day, s, e, flag):
            s = (s or "").strip(); e = (e or "").strip()
            if flag and s and e:
                db.session.add(ProfessionalAvailability(
                    professional_id=professional.id, day_of_week=day,
                    start_time=s, end_time=e, is_available=True
                ))

        for day in range(7):
            base_flag = request.form.get(f"available_{day}") == "on"
            add_window(day, request.form.get(f"start_time_{day}", ""), request.form.get(f"end_time_{day}", ""), base_flag)
            add_window(day, request.form.get(f"start_time_{day}_2", ""), request.form.get(f"end_time_{day}_2", ""), request.form.get(f"available_{day}_2") == "on" or base_flag)
            add_window(day, request.form.get(f"start_time_{day}_3", ""), request.form.get(f"end_time_{day}_3", ""), request.form.get(f"available_{day}_3") == "on" or base_flag)

        db.session.commit()
        flash("Disponibilités mises à jour avec succès!")
        return redirect(url_for("professional_availability"))

    all_avs = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    windows_by_day = {d: [] for d in range(7)}
    for av in all_avs:
        windows_by_day.get(av.day_of_week, []).append(av)
    availability_dict = {d: (windows_by_day[d][0] if windows_by_day[d] else None) for d in range(7)}

    return render_template("professional_availability.html",
                           professional=professional,
                           availabilities=availability_dict,
                           windows_by_day=windows_by_day)

# Indisponibilités ponctuelles
@app.route("/professional/unavailable-slots", methods=["GET","POST"], endpoint="professional_unavailable_slots")
@login_required
def professional_unavailable_slots():
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))

    if request.method == "POST":
        date_str = request.form.get("date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        reason = (request.form.get("reason") or "").strip()
        try:
            slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Format de date invalide"); return redirect(url_for("professional_unavailable_slots"))
        if slot_date < date.today():
            flash("Vous ne pouvez pas bloquer une date dans le passé"); return redirect(url_for("professional_unavailable_slots"))
        if not start_time or not end_time:
            flash("Heure de début et de fin obligatoires."); return redirect(url_for("professional_unavailable_slots"))

        db.session.add(UnavailableSlot(
            professional_id=professional.id,
            date=slot_date, start_time=start_time, end_time=end_time, reason=reason
        ))
        db.session.commit()
        flash("Créneau indisponible ajouté avec succès!")
        return redirect(url_for("professional_unavailable_slots"))

    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional.id)\
        .order_by(UnavailableSlot.date.desc()).all()
    return render_template("professional_unavailable_slots.html",
                           professional=professional, unavailable_slots=unavailable_slots)

@app.route("/professional/unavailable-slots/<int:slot_id>/delete", methods=["POST"], endpoint="delete_unavailable_slot")
@login_required
def delete_unavailable_slot(slot_id: int):
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))
    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional.id:
        flash("Accès non autorisé"); return redirect(url_for("professional_unavailable_slots"))
    db.session.delete(slot); db.session.commit()
    flash("Créneau indisponible supprimé!")
    return redirect(url_for("professional_unavailable_slots"))
# --- imports (laisse-les si tu les as déjà) ---
from flask import request, render_template, redirect, url_for, flash
from flask_login import login_required, current_user

# --- ROUTE: édition du profil pro ---
@app.route("/professional/profile", methods=["GET", "POST"], endpoint="professional_edit_profile")
@login_required
def professional_edit_profile():
    # Récupère ou crée le profil de façon robuste, quel que soit le schéma (user_id ou relation user)
    professional = get_or_create_professional_for_current_user(
        db, Professional, User, current_user,
        defaults={
            # Pré-remplissages doux si les champs existent dans le modèle
            "name": getattr(current_user, "username", None) or getattr(current_user, "email", None) or "Profil",
            "location": None,
            "specialty": None,
        }
    )

    if request.method == "POST":
        f = request.form

        # Textes simples
        professional.name = f.get("name", "").strip() or None
        professional.specialty = f.get("specialty", "").strip() or None
        professional.description = f.get("description", "").strip() or None
        professional.location = f.get("location", "").strip() or None
        professional.address = f.get("address", "").strip() or None
        professional.phone = f.get("phone", "").strip() or None

        # Convertisseurs tolérants
        def to_float(v):
            try:
                return float(v) if v not in (None, "",) else None
            except ValueError:
                return None

        def to_int(v):
            try:
                return int(v) if v not in (None, "",) else None
            except ValueError:
                return None

        professional.latitude  = to_float(f.get("latitude"))
        professional.longitude = to_float(f.get("longitude"))
        professional.consultation_fee = to_int(f.get("consultation_fee"))
        professional.consultation_duration_minutes = to_int(f.get("consultation_duration_minutes")) or 45
        professional.buffer_between_appointments_minutes = to_int(f.get("buffer_between_appointments_minutes")) or 15

        # Types de consultation (checkbox -> liste -> csv)
        types = f.getlist("consultation_types")  # ex: ["cabinet","en_ligne"]
        professional.consultation_types = ",".join(sorted(set(t for t in types if t)))

        # Liens sociaux (ré-approbation auto si modifiés)
        old_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        professional.facebook_url  = f.get("facebook_url", "").strip() or None
        professional.instagram_url = f.get("instagram_url", "").strip() or None
        professional.tiktok_url    = f.get("tiktok_url", "").strip() or None
        professional.youtube_url   = f.get("youtube_url", "").strip() or None
        new_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        if new_links != old_links:
            professional.social_links_approved = False  # force revalidation admin

        db.session.commit()
        flash("Profil mis à jour.", "success")
        return redirect(url_for("professional_dashboard"))

    # GET -> affiche le formulaire
    return render_template("professional_edit_profile.html", professional=professional)


# Alias “voir mes RDV”
@app.route("/professional/appointments", endpoint="professional_appointments")
@login_required
def professional_appointments():
    return redirect(url_for("my_appointments"))

@app.route("/my_appointments", endpoint="my_appointments")
@login_required
def my_appointments():
    if current_user.user_type == "professional":
        appointments = Appointment.query.join(Professional).filter(Professional.name == current_user.username).all()
    else:
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
    return render_template("my_appointments.html", appointments=appointments)

# Réservation
def _str_to_time(hhmm: str) -> dtime:
    return datetime.strptime(hhmm, "%H:%M").time()

def _add_minutes(t: dtime, minutes: int) -> dtime:
    return (datetime.combine(date.today(), t) + timedelta(minutes=minutes)).time()

def _overlap(start1: dtime, end1: dtime, start2: dtime, end2: dtime) -> bool:
    return start1 < end2 and start2 < end1

@app.route("/book_appointment/<int:professional_id>", methods=["GET","POST"], endpoint="book_appointment")
@login_required
def book_appointment(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    if professional.status != "valide":
        flash("Ce professionnel n'est pas encore validé par l'administration.")
        return redirect(url_for("professionals"))

    duration = int(getattr(professional, "consultation_duration_minutes", 45) or 45)

    if request.method == "POST":
        appointment_date = request.form.get("appointment_date", "")
        appointment_time = request.form.get("appointment_time", "")
        consultation_type = request.form.get("consultation_type", "cabinet")
        notes = request.form.get("notes", "")

        try:
            appointment_date_obj = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        except ValueError:
            flash("Format de date invalide."); return redirect(url_for("book_appointment", professional_id=professional_id))
        if appointment_date_obj < date.today():
            flash("Impossible de réserver un rendez-vous dans le passé.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        try:
            appointment_datetime = datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            flash("Format de date/heure invalide.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id, day_of_week=day_of_week, is_available=True
        ).all()

        start_t = appointment_datetime.time()
        end_t = _add_minutes(start_t, duration)

        inside_any_window = any(
            (_str_to_time(av.start_time) <= start_t) and (end_t <= _str_to_time(av.end_time))
            for av in availabilities
        )
        if not inside_any_window:
            flash("Cette heure n'est pas disponible pour ce professionnel.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        existing_confirmed = Appointment.query.filter_by(professional_id=professional_id, status="confirme")\
            .filter(db.func.date(Appointment.appointment_date) == appointment_date_obj).all()
        if any(_overlap(start_t, end_t, a.appointment_date.time(), _add_minutes(a.appointment_date.time(), duration))
               for a in existing_confirmed):
            flash("Ce créneau est déjà réservé.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        day_unavailable = UnavailableSlot.query.filter_by(professional_id=professional_id, date=appointment_date_obj).all()
        if any(_overlap(start_t, end_t, _str_to_time(s.start_time), _str_to_time(s.end_time)) for s in day_unavailable):
            flash("Ce créneau est marqué comme indisponible.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        appointment = Appointment(
            patient_id=current_user.id, professional_id=professional_id,
            appointment_date=appointment_datetime, consultation_type=consultation_type,
            status="en_attente", notes=notes
        )
        db.session.add(appointment); db.session.commit()

        # mails
        try:
            subject, text = _build_notif("pending", appointment, role="patient")
            safe_send_email(current_user.email, subject, text)
        except Exception:
            pass
        try:
            pro_user = User.query.filter_by(username=professional.name).first()
            if pro_user and pro_user.email:
                subject, text = _build_notif("pending", appointment, role="pro")
                safe_send_email(pro_user.email, subject, text)
        except Exception:
            pass

        flash("Rendez-vous réservé avec succès! Le professionnel confirmera bientôt.")
        return redirect(url_for("my_appointments"))

    availabilities = ProfessionalAvailability.query.filter_by(professional_id=professional_id, is_available=True).all()
    today = date.today()
    unavailable_dates = [
        (today + timedelta(days=i)).isoformat()
        for i in range(30)
        if UnavailableSlot.query.filter_by(professional_id=professional_id, date=(today + timedelta(days=i))).first()
    ]
    return render_template("book_appointment.html",
                           professional=professional,
                           availabilities=availabilities,
                           unavailable_dates=unavailable_dates)

# API slots
@app.route("/api/professional/<int:professional_id>/available-slots", endpoint="api_available_slots")
def api_available_slots(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    if professional.status != "valide":
        return jsonify({"error": "Professionnel non validé"}), 400

    requested_date = request.args.get("date", date.today().isoformat())
    try:
        target_date = datetime.strptime(requested_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Format de date invalide"}), 400

    day_of_week = target_date.weekday()
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id, day_of_week=day_of_week, is_available=True
    ).all()
    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional_id, date=target_date).all()
    confirmed = Appointment.query.filter_by(professional_id=professional_id, status="confirme")\
        .filter(db.func.date(Appointment.appointment_date) == target_date).all()

    duration = int(getattr(professional, "consultation_duration_minutes", 45) or 45)
    buffer_m = int(getattr(professional, "buffer_between_appointments_minutes", 15) or 15)
    step = max(1, duration + buffer_m)

    def _slots():
        out = []
        for av in availabilities:
            start_time = _str_to_time(av.start_time)
            end_time = _str_to_time(av.end_time)
            current = start_time
            while _add_minutes(current, duration) <= end_time:
                slot_start = current
                slot_end = _add_minutes(current, duration)
                is_unavailable = any(_overlap(slot_start, slot_end, _str_to_time(u.start_time), _str_to_time(u.end_time))
                                     for u in unavailable_slots)
                is_booked = any(_overlap(slot_start, slot_end, a.appointment_date.time(), _add_minutes(a.appointment_date.time(), duration))
                                for a in confirmed)
                if not is_unavailable and not is_booked:
                    out.append({"start_time": slot_start.strftime("%H:%M"),
                                "end_time": slot_end.strftime("%H:%M"),
                                "available": True})
                current = _add_minutes(current, step)
        return out

    return jsonify({
        "professional_id": professional_id,
        "date": target_date.isoformat(),
        "duration_minutes": duration,
        "buffer_minutes": buffer_m,
        "available_slots": _slots()
    })

# ========== Statut site ==========
@app.route("/site-status", endpoint="site_status")
def site_status():
    status = app.config.get("SITE_STATUS", {})
    stats = {
        "total_professionals": Professional.query.count(),
        "total_users": User.query.count(),
        "total_appointments": Appointment.query.count(),
    }
    return render_template("site_status.html", status=status, stats=stats)

# ========== Erreurs ==========
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500

# ========== Boot (migrations légères + admin seed) ==========
with app.app_context():
    db.create_all()
    try:
        # colonnes additionnelles si manquantes
        for sql in [
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS address VARCHAR(255);",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS facebook_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS instagram_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS tiktok_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS youtube_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS social_links_approved BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER DEFAULT 45;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS buffer_between_appointments_minutes INTEGER DEFAULT 15;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;",
        ]:
            db.session.execute(text(sql))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes: {e}")

    # seed admin
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@tighri.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admin_phone = os.environ.get("ADMIN_PHONE", "0663400190")
    u = User.query.filter_by(username=admin_username).first()
    if not u:
        u = User(
            username=admin_username,
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            is_admin=True,
            user_type="professional",
            phone=admin_phone
        )
        db.session.add(u); db.session.commit()
        app.logger.info("Admin '%s' créé.", admin_username)
# --- Filet de sécurité: alias si l'endpoint attendu par le template n'existe pas
if 'professional_edit_profile' not in app.view_functions:
    @app.route('/professional/profile', methods=['GET', 'POST'], endpoint='professional_edit_profile')
    @login_required
    def _professional_edit_profile_alias():
        # Si on ne sait pas quel handler utiliser, on renvoie vers le dashboard
        flash("Redirection vers votre espace professionnel.", "info")
        return redirect(url_for('professional_dashboard'))

# Pas de __main__ : Gunicorn lance app:app
