# app.py
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response, current_app, make_response
)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, date, timedelta, time as dtime
from sqlalchemy import or_, text
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import os, uuid, io, requests

# --- OAuth (Google) ---
from authlib.integrations.flask_client import OAuth

# --- Reset password: tokens & crypto ---
import secrets, hashlib

# --- Notifications (wrapper sûr) ---
from notifications import send_email as _notif_send_email
def safe_send_email(to_addr: str, subject: str, body_text: str, html: str | None = None) -> bool:
    try:
        if not to_addr:
            current_app.logger.warning("[EMAIL] destinataire manquant")
            return False
        ok = _notif_send_email(to_addr, subject, body_text, html)
        if ok:
            current_app.logger.info("[EMAIL] envoyé -> %s : %s", to_addr, subject)
        else:
            current_app.logger.error("[EMAIL] échec -> %s : %s", to_addr, subject)
        return ok
    except Exception as e:
        current_app.logger.exception("safe_send_email exception: %s", e)
        return False

# === [TIGHRI_R1:CONFIG_INLINE_SAFE] =========================================
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

BASE_DIR = Path(__file__).resolve().parent

# Racine persistante des uploads (monte un Render Disk et mets UPLOAD_ROOT=/var/data/uploads)
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = Path(UPLOAD_ROOT) / 'profiles'
ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif'}
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")
ENABLE_SMS = (os.getenv("ENABLE_SMS", "true").lower() == "true")
ENABLE_WHATSAPP = (os.getenv("ENABLE_WHATSAPP", "true").lower() == "true")
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo

# ---- Langues (compatible avec tes templates) ----
DEFAULT_LANG = os.getenv("DEFAULT_LANG", "fr")
SUPPORTED_LANGS = {"fr", "ar", "en"}
LANG_COOKIE = "lang"
# ===========================================================================

# --- App principale ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # Render est en HTTPS
app.config['PREFERRED_URL_SCHEME'] = 'https'

# --- Cookies "remember me" (Flask-Login) ---
app.config["REMEMBER_COOKIE_NAME"] = "tighri_remember"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=60)
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Dossier d’upload des images de profils (persistant)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Crée les dossiers si besoin
try:
    Path(UPLOAD_ROOT).mkdir(parents=True, exist_ok=True)
    Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)
import os
from datetime import timedelta
from typing import Optional

from flask import (
    Flask, render_template, request, redirect, url_for,
    make_response, g, send_from_directory, abort, flash
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    current_user, login_required
)
from sqlalchemy import or_, text

# -----------------------------------------------------------------------------
# App & Config
# -----------------------------------------------------------------------------
app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me")
# Render fournit DATABASE_URL (postgres). Fallback sqlite local pour dev.
db_url = os.environ.get("DATABASE_URL", "sqlite:///tighri.sqlite3")
# Render (psycopg) accepte 'postgresql://' et 'postgres://'
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=180)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# -----------------------------------------------------------------------------
# i18n minimal (cookie + injection Jinja)
# -----------------------------------------------------------------------------
SUPPORTED_LANGS = {"fr": "Français", "ar": "العربية", "en": "English"}
DEFAULT_LANG = "fr"


def _normalize_lang(code: Optional[str]) -> str:
    if not code:
        return DEFAULT_LANG
    code = code.lower().strip()
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG
# --- DB CONFIG & LANG ----
import os
from flask import g, request, make_response, redirect, url_for

# DB: forcer psycopg v3 si DATABASE_URL arrive en postgres:// ou +psycopg2
db_url = os.getenv("DATABASE_URL", "").strip()
if db_url:
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]
    if "+psycopg2" in db_url:
        db_url = db_url.replace("+psycopg2", "+psycopg")
    elif "postgresql://" in db_url and "+psycopg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://")
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Lang: expose g.current_locale (utilisé par <html lang="..."> et le label)
@app.before_request
def _load_locale():
    lang = request.cookies.get("lang", "fr").lower()
    g.current_locale = lang
    g.current_locale_label = {"fr": "Français", "ar": "العربية", "en": "English"}.get(lang, "Français")

# Route utilisée par base.html : /set-language/<lang>
@app.route("/set-language/<lang>")
def set_language(lang):
    lang = (lang or "fr").lower()
    if lang not in {"fr", "ar", "en"}:
        lang = "fr"
    resp = make_response(redirect(request.referrer or url_for("index")))
    # Cookie 1 an
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax", secure=True)
    return resp


@app.before_request
def _load_lang_from_cookie():
    lang = _normalize_lang(request.cookies.get("lang"))
    g.current_lang = lang
    g.current_lang_label = SUPPORTED_LANGS[lang]


@app.context_processor
def inject_lang():
    lang = getattr(g, "current_lang", DEFAULT_LANG)
    return {
        "current_lang": lang,
        "current_lang_label": SUPPORTED_LANGS[lang],
        "SUPPORTED_LANGS": SUPPORTED_LANGS,
    }


def _lang_response(lang_code: str, fallback_endpoint: str = "index"):
    lang = _normalize_lang(lang_code)
    resp = make_response(redirect(request.referrer or url_for(fallback_endpoint)))
    # 6 mois
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 30 * 6, httponly=False, samesite="Lax")
    return resp


@app.route("/set-language/<lang_code>")
def set_language(lang_code):
    return _lang_response(lang_code)


# tolère aussi la querystring /set-language?lang=fr
@app.route("/set-language")
def set_language_qs():
    lang_code = request.args.get("lang") or request.args.get("lang_code") or DEFAULT_LANG
    return _lang_response(lang_code)


# -----------------------------------------------------------------------------
# Modèles (souples : on tente d’importer, sinon fallback minimal)
# -----------------------------------------------------------------------------
# Si tu as déjà un fichier models.py, on l’utilise. Sinon, on crée des modèles
# simples et suffisants pour faire tourner l’app.
try:
    from models import User, Professional  # type: ignore
    HAVE_EXTERNAL_MODELS = True
except Exception:
    HAVE_EXTERNAL_MODELS = False

    class User(db.Model, UserMixin):  # type: ignore
        __tablename__ = "users"
        id = db.Column(db.Integer, primary_key=True)
        username = db.Column(db.String(80), unique=True, nullable=False)
        email = db.Column(db.String(120), unique=True, nullable=False)
        password_hash = db.Column(db.String(255), nullable=False)

    class Professional(db.Model):  # type: ignore
        __tablename__ = "professionals"
        id = db.Column(db.Integer, primary_key=True)
        full_name = db.Column(db.String(160), nullable=False)
        city = db.Column(db.String(80), nullable=True)
        specialty = db.Column(db.String(160), nullable=True)   # ex: "Psychologue"
        modes = db.Column(db.String(80), nullable=True)        # ex: "cabinet,video"
        photo_version = db.Column(db.Integer, default=0)

        # helpers facultatifs
        def has_mode(self, m: str) -> bool:
            if not self.modes:
                return False
            return m.lower() in [x.strip().lower() for x in self.modes.split(",")]

# -----------------------------------------------------------------------------
# Login manager
# -----------------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))  # type: ignore
    except Exception:
        return None

# -----------------------------------------------------------------------------
# Utilitaires pour images
# -----------------------------------------------------------------------------
AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
PLACEHOLDER_AVATAR = os.path.join(app.root_path, "static", "avatar_default.webp")


def _avatar_file_for(pid: int) -> Optional[str]:
    """Retourne un chemin absolu vers l’avatar si trouvé, sinon None."""
    if not os.path.isdir(AVATAR_DIR):
        return None
    # Essaie .webp / .jpg / .png
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        path = os.path.join(AVATAR_DIR, f"{pid}{ext}")
        if os.path.isfile(path):
            return path
    return None


# -----------------------------------------------------------------------------
# Routes “techniques”
# -----------------------------------------------------------------------------
@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
        max_age=60 * 60 * 24 * 7,
    )


@app.route("/robots.txt")
def robots():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "robots.txt",
        mimetype="text/plain",
        max_age=60 * 60 * 24 * 7,
    )


# -----------------------------------------------------------------------------
# Pages publiques
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    # Top profils (ex: 8), puis “plus” (ex: 12)
    top_professionals = (
        db.session.query(Professional)
        .order_by(Professional.id.desc())
        .limit(8)
        .all()
    )
    more_professionals = (
        db.session.query(Professional)
        .order_by(Professional.id.desc())
        .offset(8)
        .limit(12)
        .all()
    )
    return render_template(
        "index.html",
        top_professionals=top_professionals,
        more_professionals=more_professionals,
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/anthecc")
def anthecc():
    # Page simple de présentation ANTHECC
    return render_template("anthecc.html")


# -----------------------------------------------------------------------------
# Listing / recherche de professionnels
# -----------------------------------------------------------------------------
from flask import render_template, request
from sqlalchemy import or_

@app.route("/professionals")
def professionals():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    specialty = (request.args.get("specialty") or "").strip()
    mode = (request.args.get("mode") or "").strip().lower()  # cabinet / domicile / video / ""

    qry = Professional.query

    # Recherche texte "q"
    if q:
        like = f"%{q}%"
        filters = []
        if hasattr(Professional, "full_name"):
            filters.append(Professional.full_name.ilike(like))
        if hasattr(Professional, "username"):
            filters.append(Professional.username.ilike(like))
        if hasattr(Professional, "bio"):
            filters.append(Professional.bio.ilike(like))
        if filters:
            qry = qry.filter(or_(*filters))

    # Ville
    if city and hasattr(Professional, "city"):
        qry = qry.filter(Professional.city.ilike(f"%{city}%"))

    # Spécialité (champ texte côté Professional, ex: specialty / specialties_text)
    # -> Pas de join: on cherche un champ plausible. Ajuste le nom si besoin.
    if specialty:
        like = f"%{specialty}%"
        if hasattr(Professional, "specialty"):
            qry = qry.filter(Professional.specialty.ilike(like))
        elif hasattr(Professional, "specialties_text"):
            qry = qry.filter(Professional.specialties_text.ilike(like))
        # sinon : on n’applique pas de filtre spécialité (aucun join ici, volontairement)

    # Mode de consultation via booléens usuels (modifie les noms si différents chez toi)
    if mode == "cabinet" and hasattr(Professional, "mode_cabinet"):
        qry = qry.filter(Professional.mode_cabinet.is_(True))
    elif mode == "domicile" and hasattr(Professional, "mode_domicile"):
        qry = qry.filter(Professional.mode_domicile.is_(True))
    elif mode == "video" and hasattr(Professional, "mode_video"):
        qry = qry.filter(Professional.mode_video.is_(True))

    # Tri si tu as un champ rating, sinon laisse tomber
    if hasattr(Professional, "rating"):
        professionals_list = qry.order_by(Professional.rating.desc().nullslast()).all()
    else:
        professionals_list = qry.all()

    return render_template("professionals.html", professionals=professionals_list)



# -----------------------------------------------------------------------------
# Médias / Avatar & Zoom photo profil
# -----------------------------------------------------------------------------
@app.route("/media/profile/<int:professional_id>")
def media_profile(professional_id: int):
    """
    Sert l’image (zoom/pleine taille) si dispo, sinon placeholder.
    On supporte ?s=...&f=webp&v=... sans les utiliser strictement, pour compat.
    """
    file_path = _avatar_file_for(professional_id)
    if file_path and os.path.isfile(file_path):
        # envoie depuis le dossier avatars
        return send_from_directory(
            AVATAR_DIR,
            os.path.basename(file_path),
            max_age=60 * 60 * 24 * 7,
        )
    # placeholder
    if os.path.isfile(PLACEHOLDER_AVATAR):
        return send_from_directory(
            os.path.join(app.root_path, "static"),
            "avatar_default.webp",
            max_age=60 * 60 * 24 * 1,
        )
    abort(404)


@app.route("/avatar")
def avatar_proxy():
    """
    Redirection “douce” utilisée par certains templates : /avatar?professional_id=20&s=384&f=webp&v=0
    On redirige vers /media/profile/<id>, qui gère déjà la compat.
    """
    pid = request.args.get("professional_id", type=int)
    if not pid:
        abort(400)
    return redirect(url_for("media_profile", professional_id=pid), code=302)


# -----------------------------------------------------------------------------
# Auth (squelettes très simples pour ne rien casser côté templates)
# -----------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username_or_email = (request.form.get("username") or "").strip()
        user = (
            db.session.query(User)  # type: ignore
            .filter(or_(User.username == username_or_email, User.email == username_or_email))
            .first()
        )
        if user:
            login_user(user, remember=True)
            flash("Connexion réussie.", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Identifiants invalides.", "danger")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    # Simple placeholder
    if request.method == "POST":
        flash("Compte créé (exemple).", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Déconnexion réussie.", "success")
    return redirect(url_for("index"))


# -----------------------------------------------------------------------------
# Admin/Status (optionnel, affiché dans la navbar si /admin)
# -----------------------------------------------------------------------------
@app.route("/admin/status")
def site_status():
    # Exemple : statut simple
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return render_template("status.html", db_ok=db_ok)


# -----------------------------------------------------------------------------
# Erreurs
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404


@app.errorhandler(500)
def server_error(e):
    # log déjà géré par Flask. On montre une page simple.
    return render_template("errors/500.html"), 500


# -----------------------------------------------------------------------------
# Main (dev local)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    if not HAVE_EXTERNAL_MODELS:
        # En dev local, créer les tables de fallback si besoin.
        with app.app_context():
            db.create_all()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))

# --- OAuth (Google) configuration ---
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

# --- Normalisation de l'URI Postgres -> psycopg3 ---
def _normalize_pg_uri(uri: str) -> str:
    if not uri:
        return uri
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    if uri.startswith("postgresql+psycopg2://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2://"):]
    elif uri.startswith("postgresql+psycopg2cffi://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2cffi://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)
    if parsed.scheme.startswith("postgresql+psycopg") and "sslmode" not in q:
        q["sslmode"] = ["require"]
        uri = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return uri

# --- Config DB ---
from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot
from admin_server import admin_bp, ProfessionalOrder, _build_notif  # importe aussi le BP admin

uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL")
if not uri:
    raise RuntimeError("DATABASE_URL manquant : lie ta base Postgres dans Render.")
uri = _normalize_pg_uri(uri)

app.config["SQLALCHEMY_DATABASE_URI"] = uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db.init_app(app)

# --- Login manager ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Admin en Blueprint ---
app.register_blueprint(admin_bp, url_prefix='/admin')

# --- User loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== [Mini migrations & seed admin] =======================================
with app.app_context():
    db.create_all()
    try:
        # professionals: adresse + géoloc + téléphone + réseaux sociaux
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS address VARCHAR(255);"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS facebook_url TEXT;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS instagram_url TEXT;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS tiktok_url TEXT;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS youtube_url TEXT;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS social_links_approved BOOLEAN DEFAULT FALSE;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER DEFAULT 45;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS buffer_between_appointments_minutes INTEGER DEFAULT 15;"))

        # users: téléphone + oauth
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);"))
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);"))

        # users: reset password (jeton hash + expiration)
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(255);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;"))

        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes: {e}")

    # Seed admin si absent
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
        db.session.add(u)
        db.session.commit()
        app.logger.info(f"Admin '{admin_username}' créé.")
# ===========================================================================

# ===== Helpers reset mot de passe (token unique + expiration) ===============
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
    if not u:
        return None
    if not u.reset_token_expires_at or u.reset_token_expires_at < datetime.utcnow():
        return None
    return u
# ===========================================================================

# ===== [IMAGES] =============================================================
TARGET_SIZE = (512, 512)

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
        img = Image.open(io.BytesIO(raw))
        img.verify()
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Supprimer EXIF
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))

    img_square = ImageOps.fit(img_no_exif, TARGET_SIZE, Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = Path(UPLOAD_FOLDER) / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)

    return out_name
# ===========================================================================

# ===== [PACK TIGHRI R1] =====================================================
try:
    from tighri_r1 import register_tighri_r1
except Exception as e:
    app.logger.info("Pack Tighri R1 non chargé (sera ajouté plus tard). %s", e)
else:
    register_tighri_r1(
        app,
        upload_folder=str(UPLOAD_FOLDER),
        brand_name=(app.config.get('BRAND_NAME') or BRAND_NAME),
        enable_sms=bool(app.config.get('ENABLE_SMS', ENABLE_SMS)),
        enable_whatsapp=bool(app.config.get('ENABLE_WHATSAPP', ENABLE_WHATSAPP)),
        allowed_ext=ALLOWED_IMAGE_EXT,
    )
# ===========================================================================

# ====== Langue (routes compatibles avec tes templates) ======================
@app.route('/set-language/<lang_code>', endpoint='set_language', methods=['GET'])
@app.route('/set-language', endpoint='set_language', methods=['GET'])
def set_language(lang_code=None):
    """
    Accepte:
      - /set-language/<lang_code> (ex: /set-language/fr)
      - /set-language?lang=fr (compatible avec templates existants)
    """
    if not lang_code:
        lang_code = request.args.get('lang') or request.args.get('lang_code') or DEFAULT_LANG
    lang_code = (lang_code or DEFAULT_LANG).lower()
    if lang_code not in SUPPORTED_LANGS:
        lang_code = DEFAULT_LANG

    # Redirige vers la page d’origine ou l’accueil
    next_url = request.referrer or url_for('index')
    resp = make_response(redirect(next_url))
    # Cookie 6 mois
    resp.set_cookie(LANG_COOKIE, lang_code, max_age=60*60*24*180, samesite="Lax", secure=True)
    return resp

# (facultatif) filtre Jinja: lang courant utile aux templates
@app.context_processor
def inject_lang():
    lang = request.cookies.get(LANG_COOKIE, DEFAULT_LANG)
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    return {"current_lang": lang, "SUPPORTED_LANGS": SUPPORTED_LANGS}

# ======================
# Pages publiques
# ======================
@app.route('/', endpoint='index')
def index():
    """
    Accueil :
      - top_professionals : 9 pros classés (ordre admin, puis featured/rank, puis récents)
      - more_professionals : tous les autres (même tri), pour le carrousel horizontal
    Fallback si la table d'ordre n'existe pas/en erreur.
    """
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
        if top_ids:
            more_professionals = base.filter(~Professional.id.in_(top_ids)).all()
        else:
            more_professionals = base.offset(9).all()
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

    return render_template(
        'index.html',
        top_professionals=top_professionals,
        more_professionals=more_professionals
    )

@app.route('/anthecc', endpoint='anthecc')
def anthecc():
    # Page placeholder pour ne pas casser la navbar si le lien existe dans base.html
    return render_template('anthecc.html') if Path(BASE_DIR / "templates/anthecc.html").exists() else "ANTHECC", 200

@app.route('/professionals', endpoint='professionals')
def professionals():
    specialty = request.args.get('specialty', 'all')
    search_query = request.args.get('q', '')

    base_query = Professional.query.filter_by(status='valide')

    if search_query:
        like = f'%{search_query}%'
        conditions = [
            Professional.name.ilike(like),
            Professional.specialty.ilike(like),
            Professional.location.ilike(like),
            Professional.description.ilike(like),
        ]
        if hasattr(Professional, "address"):
            conditions.insert(2, Professional.address.ilike(like))
        pros = base_query.filter(or_(*conditions)).all()
    elif specialty != 'all':
        pros = base_query.filter_by(specialty=specialty).all()
    else:
        pros = base_query.all()

    return render_template('professionals.html', professionals=pros, specialty=specialty, search_query=search_query)

@app.route('/professional/<int:professional_id>', endpoint='professional_detail')
def professional_detail(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    return render_template('professional_detail.html', professional=professional)

@app.route('/about', endpoint='about')
def about():
    return render_template('about.html')

@app.route('/contact', endpoint='contact')
def contact():
    return render_template('contact.html')

# ======================
# Authentification & Comptes
# ======================
@app.route('/register', methods=['GET', 'POST'], endpoint='register')
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()

        if not username or not email or not password or not phone:
            flash("Tous les champs (dont téléphone) sont obligatoires.")
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré")
            return redirect(url_for('register'))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type='patient',
            phone=phone
        )
        db.session.add(user)
        db.session.commit()

        flash('Compte patient créé avec succès!')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/professional_register', methods=['GET', 'POST'], endpoint='professional_register')
def professional_register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        specialty = request.form.get('specialty', '').strip()
        city = request.form.get('city', '').strip()
        experience_raw = request.form.get('experience', '0')
        description = request.form.get('description', '').strip()
        fee_raw = request.form.get('consultation_fee', '0')
        phone = request.form.get('phone', '').strip()

        facebook_url  = (request.form.get('facebook_url')  or '').strip()
        instagram_url = (request.form.get('instagram_url') or '').strip()
        tiktok_url    = (request.form.get('tiktok_url')    or '').strip()
        youtube_url   = (request.form.get('youtube_url')   or '').strip()

        if not username or not email or not password or not phone:
            flash("Tous les champs obligatoires (dont téléphone) ne sont pas remplis.")
            return redirect(url_for('professional_register'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('professional_register'))
        if User.query.filter_by(email=email).first():
            flash('Email déjà enregistré')
            return redirect(url_for('professional_register'))

        try:
            experience = int((experience_raw or '0').strip())
        except ValueError:
            experience = 0
        try:
            consultation_fee = float((fee_raw or '0').replace(',', '.'))
        except ValueError:
            consultation_fee = 0.0

        try:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                user_type='professional',
                phone=phone
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
                facebook_url=facebook_url or None,
                instagram_url=instagram_url or None,
                tiktok_url=tiktok_url or None,
                youtube_url=youtube_url or None,
                social_links_approved=False,
                status='en_attente'
            )
            db.session.add(professional)

            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la création du compte professionnel. Réessayez.", "danger")
            return redirect(url_for('professional_register'))

        flash('Compte professionnel créé avec succès! Un administrateur validera votre profil.')
        return redirect(url_for('login'))

    return render_template('professional_register.html')

@app.route('/login', methods=['GET', 'POST'], endpoint='login')
def login():
    if request.method == 'POST':
        username_or_email = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = bool(request.form.get('remember'))

        user = User.query.filter(
            or_(User.username == username_or_email, User.email == username_or_email.lower())
        ).first()

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember, duration=timedelta(days=60))
            if user.user_type == 'professional':
                flash('Bienvenue dans votre espace professionnel!')
                return redirect(url_for('professional_dashboard'))
            else:
                flash('Connexion réussie!')
                return redirect(url_for('index'))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")

    return render_template('login.html')

# ---- Google OAuth: routes ----
@app.route("/auth/google")
def auth_google():
    redirect_uri = os.environ.get(
        "OAUTH_REDIRECT_URI",
        url_for("auth_google_callback", _external=True, _scheme="https")
    )
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google/callback")
def auth_google_callback():
    from models import User  # sécurité d'import circulaire

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

        user = User.query.filter(
            or_(User.oauth_sub == sub, User.email == email)
        ).first()

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
                username = f"{username_base}{i}"
                i += 1

            user = User(
                username=username,
                email=email,
                oauth_provider="google",
                oauth_sub=sub,
                full_name=name,
                picture_url=picture,
                user_type="professional"  # adapte si besoin
            )
            db.session.add(user)
            db.session.commit()

        login_user(user, remember=True, duration=timedelta(days=60))
        flash("Connexion via Google réussie ✅", "success")
        if user.user_type == 'professional':
            return redirect(url_for("professional_dashboard"))
        return redirect(url_for("index"))

    except Exception:
        flash("Connexion Google impossible. Réessayez.", "danger")
        return redirect(url_for("login"))

@app.route('/logout', endpoint='logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ===== [TIGHRI_R1:AUTH_PASSWORD_ROUTES] =====================================
@app.route('/change_password', methods=['GET', 'POST'], endpoint='change_password')
@login_required
def change_password():
    if request.method == 'POST':
        old = (request.form.get('old') or '').strip()
        new = (request.form.get('new') or '').strip()
        confirm = (request.form.get('confirm') or '').strip()

        has_local_pw = bool(current_user.password_hash)

        if has_local_pw:
            if not check_password_hash(current_user.password_hash, old):
                flash('Ancien mot de passe incorrect.', 'danger')
                return redirect(url_for('change_password'))
            if old and new and old == new:
                flash("Le nouveau mot de passe doit être différent de l'ancien.", "danger")
                return redirect(url_for('change_password'))
        else:
            if old:
                flash("Ce compte n'a pas de mot de passe local. Laissez le champ 'ancien' vide.", "warning")
                return redirect(url_for('change_password'))

        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for('change_password'))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for('change_password'))

        current_user.password_hash = generate_password_hash(new)
        db.session.commit()
        flash('Mot de passe modifié.', 'success')
        return redirect(url_for('index'))

    return render_template('change_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'], endpoint='forgot_password')
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        flash('Si le compte existe, un email de réinitialisation a été envoyé.', 'info')

        if not email:
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email).first()
        if not user:
            return redirect(url_for('login'))

        try:
            raw_token = issue_reset_token(user, hours=24)
            reset_link = url_for('reset_password', token=raw_token, _external=True, _scheme='https')

            subj = f"{BRAND_NAME} — Réinitialisation du mot de passe"
            txt = (
                f"Bonjour,\n\n"
                f"Vous avez demandé à réinitialiser votre mot de passe {BRAND_NAME}.\n"
                f"Cliquez sur ce lien (valable 24h) : {reset_link}\n\n"
                f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
            )
            html = (
                f"<p>Bonjour,</p>"
                f"<p>Vous avez demandé à réinitialiser votre mot de passe <strong>{BRAND_NAME}</strong>.</p>"
                f"<p><a href='{reset_link}'>Réinitialiser mon mot de passe</a> (valable 24&nbsp;heures)</p>"
                f"<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
            )
            safe_send_email(user.email, subj, txt, html)
        except Exception as e:
            current_app.logger.warning("forgot_password: %s", e)

        return redirect(url_for('login'))

    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'], endpoint='reset_password')
def reset_password(token):
    user = consume_token_to_user(token)
    if not user:
        flash("Lien invalide ou expiré. Refaite une demande de réinitialisation.", "danger")
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new = (request.form.get('new') or '').strip()
        confirm = (request.form.get('confirm') or '').strip()

        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for('reset_password', token=token))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for('reset_password', token=token))

        user.password_hash = generate_password_hash(new)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        db.session.commit()

        flash("Mot de passe réinitialisé. Vous pouvez vous connecter.", "success")
        return redirect(url_for('login'))

    return render_template('reset_password.html')
# ===========================================================================

# ======================
# Espace Professionnel
# ======================
@app.route('/professional_dashboard', endpoint='professional_dashboard')
@login_required
def professional_dashboard():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))

    appointments = Appointment.query.filter_by(professional_id=professional.id) \
                                    .order_by(Appointment.appointment_date.desc()) \
                                    .all()

    return render_template('professional_dashboard.html',
                           professional=professional,
                           appointments=appointments)

@app.route('/professional/profile', methods=['GET', 'POST'], endpoint='professional_edit_profile')
@login_required
def professional_edit_profile():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for('professional_dashboard'))

    if request.method == 'POST':
        # Identité / contenu
        pro.name = (request.form.get('name') or pro.name).strip()
        pro.specialty = (request.form.get('specialty') or pro.specialty or '').strip()
        pro.description = (request.form.get('description') or pro.description or '').strip()

        # Localisation
        addr = (request.form.get('address') or '').strip()
        if hasattr(pro, "address"):
            pro.address = addr

        loc = (request.form.get('location') or '').strip()
        if loc:
            pro.location = loc

        lat = (request.form.get('latitude') or '').strip()
        lng = (request.form.get('longitude') or '').strip()
        try:
            val_lat = float(lat) if lat else None
        except ValueError:
            flash("Latitude invalide", "error")
            return redirect(url_for('professional_edit_profile'))
        try:
            val_lng = float(lng) if lng else None
        except ValueError:
            flash("Longitude invalide", "error")
            return redirect(url_for('professional_edit_profile'))

        if hasattr(pro, "latitude"):
            pro.latitude = val_lat
        if hasattr(pro, "longitude"):
            pro.longitude = val_lng

        # Téléphone
        pro.phone = ((request.form.get('phone') or '').strip() or None)

        # Prix (MAD)
        fee_raw = (request.form.get('consultation_fee') or '').replace(',', '.').strip()
        if fee_raw != '':
            try:
                pro.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Tarif invalide (MAD).", "error")

        # Types de consultation
        types_list = request.form.getlist('consultation_types')
        if types_list:
            allowed = ['cabinet', 'domicile', 'en_ligne']
            cleaned = [t for t in allowed if t in set(types_list)]
            if cleaned:
                pro.consultation_types = ','.join(cleaned)

        # Liens sociaux (dés-approbation auto si modifiés)
        old_fb = getattr(pro, 'facebook_url', None)
        old_ig = getattr(pro, 'instagram_url', None)
        old_tt = getattr(pro, 'tiktok_url', None)
        old_yt = getattr(pro, 'youtube_url', None)

        new_fb = (request.form.get('facebook_url') or '').strip() or None
        new_ig = (request.form.get('instagram_url') or '').strip() or None
        new_tt = (request.form.get('tiktok_url') or '').strip() or None
        new_yt = (request.form.get('youtube_url') or '').strip() or None

        pro.facebook_url  = new_fb
        pro.instagram_url = new_ig
        pro.tiktok_url    = new_tt
        pro.youtube_url   = new_yt

        if (new_fb != old_fb) or (new_ig != old_ig) or (new_tt != old_tt) or (new_yt != old_yt):
            if hasattr(pro, 'social_links_approved'):
                pro.social_links_approved = False

        # Durée / buffer
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        if dur_raw:
            try:
                d = max(5, min(240, int(dur_raw)))
                pro.consultation_duration_minutes = d
            except ValueError:
                flash("Durée invalide (minutes).", "error")
        if buf_raw:
            try:
                b = max(0, min(120, int(buf_raw)))
                pro.buffer_between_appointments_minutes = b
            except ValueError:
                flash("Buffer invalide (minutes).", "error")

        db.session.commit()
        flash("Profil mis à jour avec succès!")
        return redirect(url_for('professional_dashboard'))

    return render_template('professional_edit_profile.html', professional=pro)

# ===== Helpers d'avatar / fallback sûrs =====
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"  # à placer dans static/img/

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

# ===== Photos de profil =====
@app.route('/media/profiles/<path:filename>', endpoint='profile_media')
def profile_media(filename):
    safe_name = os.path.basename(filename)
    file_path = Path(UPLOAD_FOLDER) / safe_name
    if file_path.exists() and file_path.is_file():
        resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=31536000"
        return resp
    return _avatar_fallback_response()

@app.route('/professional/profile/photo', methods=['GET', 'POST'], endpoint='professional_upload_photo')
@login_required
def professional_upload_photo():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for('professional_dashboard'))

    if request.method == 'POST':
        file = request.files.get('photo')
        if not file:
            flash("Veuillez sélectionner une image.", "warning")
            return redirect(url_for('professional_upload_photo'))
        try:
            saved_name = _process_and_save_profile_image(file)
            pro.image_url = f"/media/profiles/{saved_name}"
            db.session.commit()
            flash("Photo de profil mise à jour avec succès.", "success")
            return redirect(url_for('professional_dashboard'))
        except RuntimeError:
            app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow. Merci d'installer la dépendance.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")
            return redirect(url_for('professional_upload_photo'))

    return render_template('upload_photo.html')

@app.route('/professional/availability', methods=['GET', 'POST'], endpoint='professional_availability')
@login_required
def professional_availability():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))

    if request.method == 'POST':
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        def add_window(day, s, e, avail_flag):
            s = (s or '').strip()
            e = (e or '').strip()
            if avail_flag and s and e:
                av = ProfessionalAvailability(
                    professional_id=professional.id,
                    day_of_week=day,
                    start_time=s,
                    end_time=e,
                    is_available=True
                )
                db.session.add(av)

        for day in range(7):
            base_flag = request.form.get(f'available_{day}') == 'on'
            add_window(day,
                       request.form.get(f'start_time_{day}', ''),
                       request.form.get(f'end_time_{day}', ''),
                       base_flag)
            add_window(day,
                       request.form.get(f'start_time_{day}_2', ''),
                       request.form.get(f'end_time_{day}_2', ''),
                       request.form.get(f'available_{day}_2') == 'on' or base_flag)
            add_window(day,
                       request.form.get(f'start_time_{day}_3', ''),
                       request.form.get(f'end_time_{day}_3', ''),
                       request.form.get(f'available_{day}_3') == 'on' or base_flag)

        db.session.commit()
        flash('Disponibilités mises à jour avec succès!')
        return redirect(url_for('professional_availability'))

    all_avs = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    windows_by_day = {d: [] for d in range(7)}
    for av in all_avs:
        windows_by_day.get(av.day_of_week, []).append(av)
    availability_dict = {d: (windows_by_day[d][0] if windows_by_day[d] else None) for d in range(7)}

    return render_template('professional_availability.html',
                           professional=professional,
                           availabilities=availability_dict,
                           windows_by_day=windows_by_day)

@app.route('/professional/unavailable-slots', methods=['GET', 'POST'], endpoint='professional_unavailable_slots')
@login_required
def professional_unavailable_slots():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))

    if request.method == 'POST':
        date_str = request.form.get('date', '')
        start_time = request.form.get('start_time', '')
        end_time = request.form.get('end_time', '')
        reason = request.form.get('reason', '').strip()

        try:
            slot_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Format de date invalide')
            return redirect(url_for('professional_unavailable_slots'))

        if slot_date < date.today():
            flash('Vous ne pouvez pas bloquer une date dans le passé')
            return redirect(url_for('professional_unavailable_slots'))

        if not start_time or not end_time:
            flash("Heure de début et de fin obligatoires.")
            return redirect(url_for('professional_unavailable_slots'))

        slot = UnavailableSlot(
            professional_id=professional.id,
            date=slot_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason
        )
        db.session.add(slot)
        db.session.commit()

        flash('Créneau indisponible ajouté avec succès!')
        return redirect(url_for('professional_unavailable_slots'))

    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional.id) \
                                             .order_by(UnavailableSlot.date.desc()) \
                                             .all()
    return render_template('professional_unavailable_slots.html',
                           professional=professional,
                           unavailable_slots=unavailable_slots)

@app.route('/professional/unavailable-slots/<int:slot_id>/delete', methods=['POST'], endpoint='delete_unavailable_slot')
@login_required
def delete_unavailable_slot(slot_id):
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))

    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional.id:
        flash('Accès non autorisé')
        return redirect(url_for('professional_unavailable_slots'))

    db.session.delete(slot)
    db.session.commit()
    flash('Créneau indisponible supprimé!')
    return redirect(url_for('professional_unavailable_slots'))

# === Alias propre pour corriger le bouton “Voir mes RDV” sur le dashboard pro
@app.route('/professional/appointments', endpoint='professional_appointments')
@login_required
def professional_appointments():
    return redirect(url_for('my_appointments'))

@app.route('/professional/appointments/list', endpoint='professional_appointments_list')
@login_required
def professional_appointments_list():
    return redirect(url_for('my_appointments'))

@app.route('/professional/appointments/view', endpoint='professional_appointments_view')
@login_required
def professional_appointments_view():
    return redirect(url_for('my_appointments'))

# ======================
# Helpers slots (durée/buffer)
# ======================
def _str_to_time(hhmm: str) -> dtime:
    return datetime.strptime(hhmm, "%H:%M").time()

def _add_minutes(t: dtime, minutes: int) -> dtime:
    return (datetime.combine(date.today(), t) + timedelta(minutes=minutes)).time()

def _overlap(start1: dtime, end1: dtime, start2: dtime, end2: dtime) -> bool:
    return start1 < end2 and start2 < end1

# ======================
# API REST
# ======================
@app.route('/api/professionals', endpoint='api_professionals')
def api_professionals():
    pros = Professional.query.all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'consultation_fee': p.consultation_fee,
        'image_url': p.image_url,
        'specialty': p.specialty,
        'availability': p.availability,
        'address': getattr(p, 'address', None),
        'latitude': getattr(p, 'latitude', None),
        'longitude': getattr(p, 'longitude', None),
        'consultation_duration_minutes': getattr(p, 'consultation_duration_minutes', 45),
        'buffer_between_appointments_minutes': getattr(p, 'buffer_between_appointments_minutes', 15),
    } for p in pros])

@app.route('/api/professional/<int:professional_id>/available-slots', endpoint='api_available_slots')
def api_available_slots(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    if professional.status != 'valide':
        return jsonify({'error': 'Professionnel non validé'}), 400

    requested_date = request.args.get('date', date.today().isoformat())
    try:
        target_date = datetime.strptime(requested_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Format de date invalide'}), 400

    day_of_week = target_date.weekday()
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id,
        day_of_week=day_of_week,
        is_available=True
    ).all()

    unavailable_slots = UnavailableSlot.query.filter_by(
        professional_id=professional_id,
        date=target_date
    ).all()

    confirmed = Appointment.query.filter_by(
        professional_id=professional_id,
        status='confirme'
    ).filter(
        db.func.date(Appointment.appointment_date) == target_date
    ).all()

    duration = int(getattr(professional, 'consultation_duration_minutes', 45) or 45)
    buffer_m = int(getattr(professional, 'buffer_between_appointments_minutes', 15) or 15)
    step = max(1, duration + buffer_m)

    slots = []
    for availability in availabilities:
        start_time = _str_to_time(availability.start_time)
        end_time = _str_to_time(availability.end_time)

        current = start_time
        while _add_minutes(current, duration) <= end_time:
            slot_start = current
            slot_end = _add_minutes(current, duration)

            is_unavailable = any(
                _overlap(slot_start, slot_end, _str_to_time(u.start_time), _str_to_time(u.end_time))
                for u in unavailable_slots
            )

            is_booked = any(
                _overlap(
                    slot_start, slot_end,
                    a.appointment_date.time(),
                    _add_minutes(a.appointment_date.time(), duration)
                )
                for a in confirmed
            )

            if not is_unavailable and not is_booked:
                slots.append({
                    'start_time': slot_start.strftime('%H:%M'),
                    'end_time': slot_end.strftime('%H:%M'),
                    'available': True
                })

            current = _add_minutes(current, step)

    return jsonify({
        'professional_id': professional_id,
        'date': target_date.isoformat(),
        'duration_minutes': duration,
        'buffer_minutes': buffer_m,
        'available_slots': slots
    })

# ======================
# Réservation & Mes RDV
# ======================
@app.route('/book_appointment/<int:professional_id>', methods=['GET', 'POST'], endpoint='book_appointment')
@login_required
def book_appointment(professional_id):
    professional = Professional.query.get_or_404(professional_id)

    if professional.status != 'valide':
        flash("Ce professionnel n'est pas encore validé par l'administration.")
        return redirect(url_for('professionals'))

    duration = int(getattr(professional, 'consultation_duration_minutes', 45) or 45)

    if request.method == 'POST':
        appointment_date = request.form.get('appointment_date', '')
        appointment_time = request.form.get('appointment_time', '')
        consultation_type = request.form.get('consultation_type', 'cabinet')
        notes = request.form.get('notes', '')

        try:
            appointment_date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
        except ValueError:
            flash("Format de date invalide.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        if appointment_date_obj < date.today():
            flash("Impossible de réserver un rendez-vous dans le passé.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        try:
            appointment_datetime = datetime.strptime(
                f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            flash("Format de date/heure invalide.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id,
            day_of_week=day_of_week,
            is_available=True
        ).all()

        start_t = appointment_datetime.time()
        end_t = _add_minutes(start_t, duration)

        inside_any_window = any(
            (_str_to_time(av.start_time) <= start_t) and (end_t <= _str_to_time(av.end_time))
            for av in availabilities
        )
        if not inside_any_window:
            flash("Cette heure n'est pas disponible pour ce professionnel.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        existing_confirmed = Appointment.query.filter_by(
            professional_id=professional_id,
            status='confirme'
        ).filter(
            db.func.date(Appointment.appointment_date) == appointment_date_obj
        ).all()
        conflict_confirmed = any(
            _overlap(start_t, end_t, a.appointment_date.time(), _add_minutes(a.appointment_date.time(), duration))
            for a in existing_confirmed
        )
        if conflict_confirmed:
            flash("Ce créneau est déjà réservé.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        day_unavailable = UnavailableSlot.query.filter_by(
            professional_id=professional_id,
            date=appointment_date_obj
        ).all()
        conflict_unavail = any(
            _overlap(start_t, end_t, _str_to_time(s.start_time), _str_to_time(s.end_time))
            for s in day_unavailable
        )
        if conflict_unavail:
            flash("Ce créneau est marqué comme indisponible.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        appointment = Appointment(
            patient_id=current_user.id,
            professional_id=professional_id,
            appointment_date=appointment_datetime,
            consultation_type=consultation_type,
            status='en_attente',
            notes=notes
        )
        db.session.add(appointment)
        db.session.commit()

        # Notifications (user + pro par mail si dispos)
        try:
            subject, text = _build_notif('pending', appointment, role='patient')
            safe_send_email(current_user.email, subject, text)
        except Exception:
            pass

        try:
            pro_user = User.query.filter_by(username=professional.name).first()
            if pro_user and pro_user.email:
                subject, text = _build_notif('pending', appointment, role='pro')
                safe_send_email(pro_user.email, subject, text)
        except Exception:
            pass

        flash("Rendez-vous réservé avec succès! Le professionnel confirmera bientôt.")
        return redirect(url_for('my_appointments'))

    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id, is_available=True
    ).all()
    today = date.today()
    unavailable_dates = [
        (today + timedelta(days=i)).isoformat()
        for i in range(30)
        if UnavailableSlot.query.filter_by(
            professional_id=professional_id, date=(today + timedelta(days=i))
        ).first()
    ]

    return render_template('book_appointment.html',
                           professional=professional,
                           availabilities=availabilities,
                           unavailable_dates=unavailable_dates)

@app.route('/my_appointments', endpoint='my_appointments')
@login_required
def my_appointments():
    if current_user.user_type == 'professional':
        appointments = Appointment.query.join(Professional).filter(
            Professional.name == current_user.username
        ).all()
    else:
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
    return render_template('my_appointments.html', appointments=appointments)

# ===== [CRON REMINDER 24h] ==================================================
@app.get('/cron/send-reminders-24h', endpoint='cron_send_reminders_24h')
def cron_send_reminders_24h():
    token = request.args.get('token', '')
    if token != os.environ.get('CRON_TOKEN', 'dev'):
        return jsonify({'ok': False, 'error': 'unauthorized'}), 403

    now = datetime.utcnow()
    start = now + timedelta(hours=24)
    end = now + timedelta(hours=25)

    rows = (db.session.query(Appointment)
            .filter(Appointment.status == 'confirme')
            .filter(Appointment.appointment_date >= start,
                    Appointment.appointment_date < end)
            .all())
    for ap in rows:
        try:
            subject, text = _build_notif('reminder', ap, role='patient')
            user = User.query.get(ap.patient_id)
            safe_send_email(getattr(user, 'email', None), subject, text)
        except Exception:
            pass
    return jsonify({'ok': True, 'reminders_sent': len(rows)})

# ======================
# Site Status
# ======================
@app.route('/site-status', endpoint='site_status')
def site_status():
    status = app.config.get('SITE_STATUS', {})
    stats = {
        'total_professionals': Professional.query.count(),
        'total_users': User.query.count(),
        'total_appointments': Appointment.query.count(),
        'database_file': 'tighri.db',
        'server_port': 5000,
        'admin_port': 8080
    }
    return render_template('site_status.html', status=status, stats=stats)

# ===== Proxy d’images pour photos de profils =====
@app.route("/media/profile/<int:professional_id>", endpoint='profile_photo')
def profile_photo(professional_id):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

    if raw_url.startswith("/media/profiles/"):
        fname = raw_url.split("/media/profiles/")[-1]
        return redirect(url_for('profile_media', filename=fname, _external=True, _scheme='https'))

    if not raw_url:
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
    data = r.content

    resp = Response(data, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

# === Alias rétro-compatible pour l'ancien endpoint "avatar" ===
@app.route("/avatar", endpoint="avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# ===== Favicon (évite le 404) ==============================
@app.route("/favicon.ico")
def favicon():
    fav_path = Path(app.static_folder or (BASE_DIR / "static")) / "favicon.ico"
    if fav_path.exists():
        resp = send_from_directory(app.static_folder, "favicon.ico", conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp
    return ("", 204)

# Pas de bloc __main__ (gunicorn utilise app:app)
