# app.py — Tighri (contrat fixe : ORM simple, familles/spécialités unifiées, multi-sélection + ajout-si-absent)

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

# =========================
#   CONSTANTES / DOSSIERS
# =========================
BASE_DIR = Path(__file__).resolve().parent
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = UPLOAD_ROOT / "profiles"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif"}
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo

# =========================
#   FLASK APP
# =========================
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
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config["UPLOAD_FOLDER"] = str(UPLOAD_FOLDER)
app.config.setdefault("MAX_CONTENT_LENGTH", MAX_CONTENT_LENGTH)

# Crée les dossiers d’upload si besoin
try:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)

# =========================
#   DB / MODELS
# =========================
def _normalize_pg_uri(uri: str) -> str:
    if not uri:
        return uri
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    # forcer psycopg3
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

# ⬇️ Importe City / Specialty pour correspondre à ton models.py
from models import (
    db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot,
    City, Specialty
)

uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL") or ""
if not uri:
    raise RuntimeError("DATABASE_URL manquant : lie ta base Postgres dans Render.")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_pg_uri(uri)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db.init_app(app)

# =========================
#   ADMIN BLUEPRINT
# =========================
from admin_server import admin_bp, ProfessionalOrder, _build_notif
app.register_blueprint(admin_bp, url_prefix="/admin")

# =========================
#   LOGIN MANAGER
# =========================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def _load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

# =========================
#   I18N / LANG
# =========================
DEFAULT_LANG = "fr"
SUPPORTED_LANGS = {"fr", "en", "ar"}

LEGACY_LANG_COOKIE = "lang"
LANG_COOKIE = "tighri_lang"
LANG_MAX_AGE = 60 * 60 * 24 * 180

def _normalize_lang(code: str | None):
    if not code:
        return DEFAULT_LANG
    v = str(code).strip().lower()
    if "-" in v:
        v = v.split("-", 1)[0]
    return v if v in SUPPORTED_LANGS else DEFAULT_LANG

def _cookie_domain_for(host: str | None):
    if not host:
        return None
    host = host.split(":")[0]
    if host in ("localhost",) or host.replace(".", "").isdigit():
        return None
    parts = host.split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return None

@app.before_request
def _load_locale():
    param = request.args.get("lang")
    cookie_new = request.cookies.get(LANG_COOKIE)
    cookie_old = request.cookies.get(LEGACY_LANG_COOKIE)
    accept = request.accept_languages.best_match(SUPPORTED_LANGS) if request.accept_languages else None
    lang = param or cookie_new or cookie_old or accept
    g.current_locale = _normalize_lang(lang)

@app.after_request
def _vary_on_cookie_for_lang(resp):
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        existing_vary = resp.headers.get("Vary")
        resp.headers["Vary"] = "Cookie" if not existing_vary else f"{existing_vary}, Cookie"
        resp.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

@app.route("/set-language/clear")
def clear_language_cookie():
    resp = make_response(redirect(request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.delete_cookie(LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

TRANSLATIONS = {
    "fr": {
        "nav": {"home": "Accueil", "professionals": "Professionals", "anthecc": "ANTHECC", "about": "À propos", "contact": "Contact"},
        "auth": {"login": "Connexion", "register": "Inscription", "logout": "Déconnexion"},
        "common": {"menu": "menu"},
        "home": {"title": "Tighri", "tagline": "La plateforme marocaine pour prendre rendez-vous avec des psychologues, thérapeutes et coachs certifiés"},
        "search": {"cta": "Rechercher", "mode": "Mode", "city": "Ville", "specialty": "Spécialité", "q": "Nom, mot-clé..."},
        "cards": {"patient": "Espace Patient", "pro": "Espace Professionnel"},
    },
    "en": {
        "nav": {"home": "Home", "professionals": "Professionals", "anthecc": "ANTHECC", "about": "About", "contact": "Contact"},
        "auth": {"login": "Login", "register": "Sign up", "logout": "Logout"},
        "common": {"menu": "menu"},
        "home": {"title": "Tighri", "tagline": "Moroccan platform to book certified psychologists, therapists and coaches"},
        "search": {"cta": "Search", "mode": "Mode", "city": "City", "specialty": "Specialty", "q": "Name, keyword..."},
        "cards": {"patient": "Patient Space", "pro": "Professional Space"},
    },
    "ar": {
        "nav": {"home": "الرئيسية", "professionals": "المهنيون", "anthecc": "ANTHECC", "about": "حول", "contact": "اتصل"},
        "auth": {"login": "تسجيل الدخول", "register": "إنشاء حساب", "logout": "تسجيل الخروج"},
        "common": {"menu": "القائمة"},
        "home": {"title": "تيغري", "tagline": "منصة مغربية لحجز مواعيد مع أخصائيين ومعالجين ومدربين معتمدين"},
        "search": {"cta": "ابحث", "mode": "النمط", "city": "المدينة", "specialty": "التخصص", "q": "اسم، كلمة..."},
        "cards": {"patient": "فضاء المريض", "pro": "فضاء المهني"},
    },
}

def _get_in(d, parts):
    cur = d
    for p in parts:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur

def t(key, default=None, **kwargs):
    lang = getattr(g, "current_locale", DEFAULT_LANG)
    parts = str(key).split(".")
    val = _get_in(TRANSLATIONS.get(lang, {}), parts)
    if val is None:
        val = _get_in(TRANSLATIONS.get("fr", {}), parts)
    if val is None:
        val = default if default is not None else parts[-1]
    if kwargs:
        try:
            val = val.format(**kwargs)
        except Exception:
            pass
    return val

def _lang_label(lang):
    return {"fr": "Français", "en": "English", "ar": "العربية"}.get(lang, "Français")

def _text_dir(lang):
    return "rtl" if lang == "ar" else "ltr"

@app.context_processor
def inject_i18n():
    lang = getattr(g, "current_locale", DEFAULT_LANG)
    return {"t": t, "current_lang": lang, "current_lang_label": _lang_label(lang), "text_dir": _text_dir(lang)}

@app.route("/set-language/<lang_code>")
def set_language(lang_code):
    nxt = request.args.get("next") or request.referrer or url_for("index")
    return redirect(url_for("set_language_qs", lang=lang_code, next=nxt))

# --- Helpers SQL utilitaires (gardé si besoin ailleurs)
from sqlalchemy import text as _t
def _fetch_list(sql):
    return [dict(r) for r in db.session.execute(_t(sql))]

@app.route("/set_language")
def set_language_fallback():
    lang_code = request.args.get("lang")
    nxt = request.args.get("next") or request.referrer or url_for("index")
    if not lang_code:
        return redirect(nxt)
    return redirect(url_for("set_language_qs", lang=lang_code, next=nxt))

@app.route("/set-language/<code>")
def set_language_path(code):
    code = _normalize_lang(code)
    resp = make_response(redirect(request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.set_cookie(LANG_COOKIE, code, max_age=LANG_MAX_AGE, httponly=False, secure=True, samesite="Lax", domain=dom, path="/")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

@app.route("/set-language")
def set_language_qs():
    code = _normalize_lang(request.args.get("lang"))
    resp = make_response(redirect(request.args.get("next") or request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.set_cookie(LANG_COOKIE, code, max_age=LANG_MAX_AGE, httponly=False, secure=True, samesite="Lax", domain=dom, path="/")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

# =========================
#   ⚙️ CANONICAL HOST
# =========================
PRIMARY_HOST = os.getenv("PRIMARY_HOST", "www.tighri.ma")

@app.before_request
def _enforce_primary_domain():
    host = request.host.split(":")[0]
    if host != PRIMARY_HOST:
        return redirect(request.url.replace(host, PRIMARY_HOST, 1), code=301)

# =========================
#   EMAILS (safe wrapper)
# =========================
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

# =========================
#   PIL (images)
# =========================
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
PLACEHOLDER_AVATAR = os.path.join(app.root_path, "static", "avatar_default.webp")
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"

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
    try:
        img = Image.open(io.BytesIO(raw)); img.verify()
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
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

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

# =========================
#   SERVICE FICHIERS (Render Disk)
# =========================
@app.route("/u/profiles/<path:filename>", endpoint="u_profiles")
def u_profiles(filename: str):
    if not filename or ".." in filename or filename.startswith("/"):
        abort(404)
    fpath = UPLOAD_FOLDER / os.path.basename(filename)
    if not fpath.exists():
        return _avatar_fallback_response()
    resp = send_from_directory(str(UPLOAD_FOLDER), os.path.basename(filename), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000"
    return resp

def _normalize_disk_url(value: str | None) -> Optional[str]:
    """
    Accepte :
      - '/media/profiles/abc.jpg'
      - 'abc.jpg'
      - URL http(s)
    Retourne une URL servie par l’app si possible.
    """
    if not value:
        return None
    v = value.strip()
    if v.startswith("http://") or v.startswith("https://"):
        if v.startswith("http://"):
            v = "https://" + v[len("http://"):]
        return v
    if v.startswith("/media/profiles/"):
        v = v.split("/media/profiles/", 1)[-1]
    return url_for("u_profiles", filename=os.path.basename(v))

def _pro_photo_field(pro: Professional, index: int) -> Optional[str]:
    candidates_by_index = {
        1: ("image_url", "photo_main", "avatar_url"),
        2: ("image_url2", "photo_alt1", "gallery1", "gallery_1", "photo2", "photo_secondaire1"),
        3: ("image_url3", "photo_alt2", "gallery2", "gallery_2", "photo3", "photo_secondaire2"),
    }
    for field in candidates_by_index.get(index, ()):
        if hasattr(pro, field):
            val = getattr(pro, field)
            if val:
                return str(val)
    return None

def professional_photo_url(pro: Professional, index: int) -> Optional[str]:
    raw = _pro_photo_field(pro, index)
    if raw:
        return _normalize_disk_url(raw)
    if index == 1 and not raw:
        return url_for("profile_photo", professional_id=pro.id)
    return None

def professional_gallery_urls(pro: Professional) -> list[str]:
    urls = []
    for i in (1, 2, 3):
        u = professional_photo_url(pro, i)
        if u:
            urls.append(u)
    return urls

@app.context_processor
def inject_gallery_helpers():
    return {
        "professional_photo_url": professional_photo_url,
        "professional_gallery_urls": professional_gallery_urls,
    }

# =========================
#   LISTES (ORM + seeds)
# =========================
try:
    from seeds_taxonomy import (
        SPECIALTY_FAMILIES,
        CITY_OBJECTS,
        ALL_CITIES as SEED_CITIES,
        ALL_SPECIALTIES as SEED_SPECIALTIES,
    )
except Exception:
    SPECIALTY_FAMILIES = []
    CITY_OBJECTS = []
    SEED_CITIES = ["Casablanca", "Rabat", "Marrakech", "Fès", "Tanger", "Agadir"]
    SEED_SPECIALTIES = [
        "Psychologue", "Psychiatre", "Psychothérapeute", "Coach",
        "Orthophoniste", "Psychomotricien", "Kinésithérapeute"
    ]

def _ui_cities():
    try:
        return [{"id": c.id, "name": c.name} for c in City.query.order_by(City.name.asc()).all()]
    except Exception:
        return []

def _ui_specialties():
    try:
        return [{"id": s.id, "name": s.name, "category": s.category} for s in Specialty.query.order_by(Specialty.name.asc()).all()]
    except Exception:
        return []

def _ui_families_rows():
    try:
        rows = (
            db.session.query(Specialty.category)
            .filter(Specialty.category.isnot(None), Specialty.category != "")
            .distinct()
            .order_by(Specialty.category.asc())
            .all()
        )
        out = []
        for i, r in enumerate(rows, start=1):
            out.append({"id": i, "name": r[0]})
        return out
    except Exception:
        return []

@app.context_processor
def inject_taxonomies_for_forms():
    return {
        "ALL_CITIES": SEED_CITIES,
        "ALL_SPECIALTIES": SEED_SPECIALTIES,
    }

# =========================
#   ROUTES TECH
# =========================
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

# =========================
#   PAGES PUBLIQUES
# =========================
@app.route("/", endpoint="index")
def index():
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

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_template("index.html",
        top_professionals=top_professionals,
        more_professionals=more_professionals,
        cities=cities, families=families, specialties=specialties
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

@app.route("/professionals", endpoint="professionals")
def professionals():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    city_id = request.args.get("city_id", type=int)

    family = (request.args.get("family") or "").strip()

    specialty = (request.args.get("specialty") or "").strip()
    specialty_id = request.args.get("specialty_id", type=int)
    mode = (request.args.get("mode") or "").strip().lower()

    if mode == "visio":
        mode = "en_ligne"

    qry = Professional.query.filter_by(status='valide')

    if q:
        like = f"%{q}%"
        conds = []
        for attr in ("name", "full_name", "description", "specialty", "location", "address"):
            if hasattr(Professional, attr):
                conds.append(getattr(Professional, attr).ilike(like))
        if conds:
            qry = qry.filter(or_(*conds))

    if city_id is not None and hasattr(Professional, "city_id"):
        qry = qry.filter(Professional.city_id == city_id)
    elif city and hasattr(Professional, "location"):
        qry = qry.filter(Professional.location.ilike(f"%{city}%"))

    if specialty_id is not None and hasattr(Professional, "primary_specialty_id"):
        qry = qry.filter(Professional.primary_specialty_id == specialty_id)
    elif specialty and hasattr(Professional, "specialty"):
        qry = qry.filter(Professional.specialty.ilike(f"%{specialty}%"))

    if family:
        like_family = family
        qry = qry.filter(
            db.or_(
                Professional.primary_specialty.has(Specialty.category.ilike(like_family)),
                Professional.specialties.any(Specialty.category.ilike(like_family)),
                Professional.specialty.ilike(f"%{family}%"),
            )
        )

    if mode and hasattr(Professional, "consultation_types"):
        qry = qry.filter(Professional.consultation_types.ilike(f"%{mode}%"))

    pros = qry.order_by(Professional.is_featured.desc(), Professional.created_at.desc()).all()

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_template("professionals.html",
                           professionals=pros,
                           specialty=specialty, search_query=q,
                           cities=cities, families=families, specialties=specialties)

@app.route("/professional/<int:professional_id>", endpoint="professional_detail")
def professional_detail(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    return render_template("professional_detail.html", professional=professional)

# =========================
#   MÉDIAS / PHOTOS
# =========================
@app.route("/media/profile/<int:professional_id>", endpoint="profile_photo")
def profile_photo(professional_id: int):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

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
        file_path = _avatar_file_for(professional_id)
        if file_path and os.path.isfile(file_path):
            return send_from_directory(AVATAR_DIR, os.path.basename(file_path), max_age=60*60*24*7)
        if os.path.isfile(PLACEHOLDER_AVATAR):
            return send_from_directory(os.path.join(app.root_path, "static"), "avatar_default.webp", max_age=86400)
        return _avatar_fallback_response()

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

@app.route("/media/profile/<int:professional_id>/<int:index>", endpoint="profile_photo_n")
def profile_photo_n(professional_id: int, index: int):
    if index not in (1, 2, 3):
        abort(404)
    pro = Professional.query.get_or_404(professional_id)
    raw = _pro_photo_field(pro, index)
    if index == 1 and not raw:
        return redirect(url_for("profile_photo", professional_id=professional_id))

    url = _normalize_disk_url(raw) if raw else None

    if url and (url.startswith("http://") or url.startswith("https://")):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        try:
            r = requests.get(url, timeout=8, stream=True)
            r.raise_for_status()
        except Exception:
            return _avatar_fallback_response()
        resp = Response(r.content, mimetype=r.headers.get("Content-Type", "image/jpeg"))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    if url:
        fname = url.split("/u/profiles/")[-1]
        fpath = UPLOAD_FOLDER / os.path.basename(fname)
        if fpath.exists():
            resp = send_from_directory(str(UPLOAD_FOLDER), os.path.basename(fname), conditional=True)
            resp.headers["Cache-Control"] = "public, max-age=31536000"
            return resp

    return _avatar_fallback_response()

@app.route("/avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id: int):
    return redirect(url_for("profile_photo", professional_id=professional_id))

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

    return render_template("upload_photo.html", professional=pro)

@app.route("/professional/profile/photo/<int:index>", methods=["GET", "POST"], endpoint="professional_upload_photo_n")
@login_required
def professional_upload_photo_n(index: int):
    if current_user.user_type != "professional" or index not in (1, 2, 3):
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
            return redirect(url_for("professional_upload_photo_n", index=index))
        try:
            saved_name = _process_and_save_profile_image(file)
            field = "image_url" if index == 1 else ("image_url2" if index == 2 else "image_url3")
            setattr(pro, field, f"/media/profiles/{saved_name}")
            db.session.commit()
            flash(f"Photo #{index} mise à jour avec succès.", "success")
            return redirect(url_for("professional_dashboard"))
        except RuntimeError:
            current_app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            current_app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")

    return render_template("upload_photo.html", professional=pro, index=index)

@app.route("/professional/profile/photos-upload", methods=["POST"], endpoint="professional_photos_upload")
@login_required
def professional_photos_upload_alias():
    return professional_upload_photo()

# =========================
#   AUTH LOCAL
# =========================
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

        city_id = request.form.get("city_id", type=int)
        primary_specialty_id = request.form.get("primary_specialty_id", type=int) or request.form.get("specialty_id", type=int)

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
            if city_id is not None and hasattr(professional, "city_id"):
                professional.city_id = city_id
            if primary_specialty_id is not None and hasattr(professional, "primary_specialty_id"):
                professional.primary_specialty_id = primary_specialty_id

            spec_ids = [int(x) for x in request.form.getlist("specialty_ids") if str(x).isdigit()]

            new_name = (request.form.get("new_specialty_name") or "").strip()
            new_family = (request.form.get("new_specialty_family") or "").strip()
            if new_name:
                existing = Specialty.query.filter(db.func.lower(Specialty.name) == new_name.lower()).first()
                if not existing:
                    existing = Specialty(name=new_name, category=(new_family or None))
                    db.session.add(existing)
                    db.session.flush()
                spec_ids.append(existing.id)

            primary_spec_id = request.form.get("primary_specialty_id", type=int)
            if primary_spec_id:
                professional.primary_specialty_id = primary_spec_id
            elif not getattr(professional, "primary_specialty_id", None) and spec_ids:
                professional.primary_specialty_id = spec_ids[0]

            if spec_ids:
                professional.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all()

            if professional.primary_specialty_id and not (professional.specialty or "").strip():
                ps = db.session.get(Specialty, professional.primary_specialty_id)
                if ps:
                    professional.specialty = ps.name

            db.session.add(professional)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la création du compte professionnel. Réessayez.", "danger")
            return redirect(url_for("professional_register"))

        flash("Compte professionnel créé avec succès! Un administrateur validera votre profil.")
        return redirect(url_for("login"))

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()
    return render_template("professional_register.html",
                           cities=cities, families=families, specialties=specialties)

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

# =========================
#   OAUTH GOOGLE
# =========================
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

# =========================
#   RESET PASSWORD
# =========================
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

# =========================
#   ESPACE PRO / RDV
# =========================
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

# Edition profil pro (conservatif, avec grâce sur les numériques)
@app.route("/professional/profile", methods=["GET", "POST"], endpoint="professional_edit_profile")
@login_required
def professional_edit_profile():
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        professional = Professional(name=current_user.username, description="Profil en cours de complétion.", status="en_attente")
        db.session.add(professional); db.session.commit()

    if request.method == "POST":
        f = request.form
        professional.name = f.get("name", "").strip() or professional.name
        professional.specialty = f.get("specialty", "").strip() or professional.specialty   # legacy
        professional.description = f.get("description", "").strip() or professional.description
        professional.location = f.get("location", "").strip() or professional.location       # legacy
        professional.address = f.get("address", "").strip() or professional.address
        professional.phone = f.get("phone", "").strip() or professional.phone

        # FK si dispo
        city_id = f.get("city_id", type=int)
        if city_id is not None and hasattr(professional, "city_id"):
            professional.city_id = city_id
        ps_id = f.get("primary_specialty_id", type=int) or f.get("specialty_id", type=int)
        if ps_id is not None and hasattr(professional, "primary_specialty_id"):
            professional.primary_specialty_id = ps_id

        # multi-sélection & ajout-si-absent
        spec_ids = [int(x) for x in f.getlist("specialty_ids") if str(x).isdigit()]

        new_name = (f.get("new_specialty_name") or "").strip()
        new_family = (f.get("new_specialty_family") or "").strip()
        if new_name:
            existing = Specialty.query.filter(db.func.lower(Specialty.name) == new_name.lower()).first()
            if not existing:
                existing = Specialty(name=new_name, category=(new_family or None))
                db.session.add(existing)
                db.session.flush()
            spec_ids.append(existing.id)

        primary_spec_id = f.get("primary_specialty_id", type=int)
        if primary_spec_id:
            professional.primary_specialty_id = primary_spec_id
        elif not getattr(professional, "primary_specialty_id", None) and spec_ids:
            professional.primary_specialty_id = spec_ids[0]

        if spec_ids:
            professional.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all()

        if professional.primary_specialty_id and not (professional.specialty or "").strip():
            ps = db.session.get(Specialty, professional.primary_specialty_id)
            if ps:
                professional.specialty = ps.name

        # Helpers numériques "gracieux"
        def parse_int_or_keep(v_str: Optional[str], old_val: Optional[int], default_if_invalid: Optional[int]=None) -> Optional[int]:
            v = (v_str or "").strip()
            if v == "":
                return old_val
            v = v.replace(",", ".")
            try:
                return int(float(v))
            except ValueError:
                return old_val if old_val is not None else default_if_invalid

        def parse_float_or_keep(v_str: Optional[str], old_val: Optional[float], default_if_invalid: Optional[float]=None) -> Optional[float]:
            v = (v_str or "").strip()
            if v == "":
                return old_val
            v = v.replace(",", ".")
            try:
                return float(v)
            except ValueError:
                return old_val if old_val is not None else default_if_invalid

        professional.latitude  = parse_float_or_keep(f.get("latitude"),  getattr(professional, "latitude", None))
        professional.longitude = parse_float_or_keep(f.get("longitude"), getattr(professional, "longitude", None))

        # ⬇️ Ne jamais envoyer NULL si champ laissé vide (évite NOT NULL violation)
        professional.consultation_fee = parse_int_or_keep(
            f.get("consultation_fee"),
            getattr(professional, "consultation_fee", 0),
            default_if_invalid=0
        )

        professional.consultation_duration_minutes = parse_int_or_keep(
            f.get("consultation_duration_minutes"),
            getattr(professional, "consultation_duration_minutes", 45),
            default_if_invalid=45
        ) or 45

        professional.buffer_between_appointments_minutes = parse_int_or_keep(
            f.get("buffer_between_appointments_minutes"),
            getattr(professional, "buffer_between_appointments_minutes", 15),
            default_if_invalid=15
        ) or 15

        # Types de consultation : si aucune valeur postée, on conserve l'existant
        posted_types = [t for t in f.getlist("consultation_types") if t]
        if posted_types:
            professional.consultation_types = ",".join(sorted(set(posted_types)))

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
            professional.social_links_approved = False

        db.session.commit()
        flash("Profil mis à jour.", "success")
        return redirect(url_for("professional_dashboard"))

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_template("professional_edit_profile.html",
                           professional=professional,
                           cities=cities, families=families, specialties=specialties)

# ===== RDV côté PRO : liste + filtres =====
@app.route("/professional/appointments", methods=["GET"], endpoint="professional_appointments")
@login_required
def professional_appointments():
    if current_user.user_type != "professional":
        flash("Accès non autorisé")
        return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("professional_dashboard"))

    status = (request.args.get("status") or "all").strip()
    scope  = (request.args.get("scope")  or "upcoming").strip()

    q = Appointment.query.filter_by(professional_id=pro.id)
    now = datetime.utcnow()

    if scope == "upcoming":
        q = q.filter(Appointment.appointment_date >= now)
    elif scope == "past":
        q = q.filter(Appointment.appointment_date < now)

    if status in ("en_attente", "confirme", "annule"):
        q = q.filter_by(status=status)

    appointments = q.order_by(Appointment.appointment_date.desc()).all()

    return render_template(
        "professional_appointments.html",
        appointments=appointments,
        status=status,
        scope=scope
    )

# ===== Actions côté PRO sur un RDV =====
@app.route("/professional/appointments/<int:appointment_id>/<action>", methods=["POST"], endpoint="professional_appointment_action")
@login_required
def professional_appointment_action(appointment_id, action):
    if current_user.user_type != "professional":
        abort(403)

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        abort(403)

    ap = Appointment.query.get_or_404(appointment_id)
    if ap.professional_id != pro.id:
        abort(403)

    if action == "accept":
        ap.status = "confirme"
        flash("Rendez-vous confirmé.", "success")
    elif action in ("reject", "cancel"):
        ap.status = "annule"
        flash("Rendez-vous annulé.", "warning")
    elif action == "ask-reschedule":
        ap.status = "en_attente"
        flash("Demande de report envoyée (statut repassé en attente).", "info")
    else:
        abort(400)

    db.session.commit()

    try:
        subj, txt = _build_notif(
            "accepted" if ap.status == "confirme" else ("refused" if ap.status == "annule" else "pending"),
            ap, role="patient"
        )
        patient = User.query.get(ap.patient_id)
        if patient and patient.email:
            safe_send_email(patient.email, subj, txt)

        pro_user = User.query.filter_by(username=pro.name).first()
        if pro_user and pro_user.email:
            subj2, txt2 = _build_notif(
                "accepted" if ap.status == "confirme" else ("refused" if ap.status == "annule" else "pending"),
                ap, role="pro"
            )
            safe_send_email(pro_user.email, subj2, txt2)
    except Exception:
        pass

    return redirect(url_for(
        "professional_appointments",
        status=request.args.get("status", "all"),
        scope=request.args.get("scope", "upcoming")
    ))

# Alias rendez-vous (PATIENT & fallback)
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

# =========================
#   STATUT / ERREURS
# =========================
@app.route("/site-status", endpoint="site_status")
def site_status():
    status = app.config.get("SITE_STATUS", {})
    stats = {
        "total_professionals": Professional.query.count(),
        "total_users": User.query.count(),
        "total_appointments": Appointment.query.count(),
    }
    return render_template("site_status.html", status=status, stats=stats)

@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500

# =========================
#   BOOT (migrations légères + admin seed + TAXONOMIE)
# =========================
def _bootstrap_taxonomy():
    inserted_cities = 0
    inserted_specs = 0
    updated_categ = 0

    try:
        for obj in CITY_OBJECTS:
            name = (obj.get("name_fr") or obj.get("name") or "").strip()
            if not name:
                continue
            exists = City.query.filter(db.func.lower(City.name) == name.lower()).first()
            if not exists:
                db.session.add(City(name=name))
                inserted_cities += 1
    except Exception as e:
        current_app.logger.warning("Bootstrap villes: %s", e)

    try:
        for fam in SPECIALTY_FAMILIES:
            cat = (fam.get("name_fr") or "").strip()
            for sp in fam.get("specialties", []):
                sp_name = (sp.get("name_fr") or sp.get("name") or "").strip()
                if not sp_name:
                    continue
                row = Specialty.query.filter(db.func.lower(Specialty.name) == sp_name.lower()).first()
                if not row:
                    db.session.add(Specialty(name=sp_name, category=cat))
                    inserted_specs += 1
                else:
                    if not (row.category or "").strip():
                        row.category = cat
                        updated_categ += 1
    except Exception as e:
        current_app.logger.warning("Bootstrap spécialités: %s", e)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning("Bootstrap taxonomy commit: %s", e)

    current_app.logger.info(
        "Taxonomy seed → villes +%d, spécialités +%d, catégories complétées %d",
        inserted_cities, inserted_specs, updated_categ
    )

with app.app_context():
    db.create_all()
    try:
        stmts = [
            # colonnes additionnelles (idempotent)
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
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS featured_rank INTEGER;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS certified_tighri BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS approved_anthecc BOOLEAN DEFAULT FALSE;",

            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;",

            # FK facultatives
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id) ON DELETE SET NULL;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS primary_specialty_id INTEGER REFERENCES specialties(id) ON DELETE SET NULL;",

            # Photos secondaires
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url2 TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url3 TEXT;",
        ]
        for sql in stmts:
            db.session.execute(text(sql))

        # Normalisation douce sur consultation_fee (évite crash si NULL historique)
        try:
            db.session.execute(text("UPDATE professionals SET consultation_fee = 0 WHERE consultation_fee IS NULL;"))
            db.session.execute(text("ALTER TABLE professionals ALTER COLUMN consultation_fee SET DEFAULT 0;"))
        except Exception as e:
            current_app.logger.warning(f"consultation_fee default/normalize: {e}")

        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes: {e}")

    # --- Taxonomy étendue
    try:
        _bootstrap_taxonomy()
    except Exception as e:
        app.logger.warning("Bootstrap taxonomy failed, fallback minimal: %s", e)
        if Specialty.query.count() == 0:
            for name in SEED_SPECIALTIES:
                try:
                    db.session.add(Specialty(name=name))
                except Exception:
                    pass
            db.session.commit()
        if City.query.count() == 0:
            for name in SEED_CITIES:
                try:
                    db.session.add(City(name=name))
                except Exception:
                    pass
            db.session.commit()

    # --- Admin par défaut
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
from pro_office import pro_office_bp      # nouveau blueprint "Bureau virtuel"
from patient_portal import patient_bp     # nouveau blueprint "Espace patient"

app.register_blueprint(pro_office_bp, url_prefix="/pro/office")
app.register_blueprint(patient_bp,    url_prefix="/patient")

# Pas de __main__: Gunicorn lance app:app
