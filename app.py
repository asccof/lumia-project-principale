from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response
)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, date, timedelta, time as dtime
from sqlalchemy import or_, text
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
import os, uuid, io, requests

# === [TIGHRI_R1:CONFIG_INLINE_SAFE] =========================================
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

try:
    BASE_DIR
except NameError:
    BASE_DIR = Path(__file__).resolve().parent

try:
    UPLOAD_FOLDER
except NameError:
    UPLOAD_FOLDER = BASE_DIR / 'uploads' / 'profiles'

try:
    ALLOWED_IMAGE_EXT
except NameError:
    ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif'}

try:
    BRAND_NAME
except NameError:
    BRAND_NAME = 'Tighri'

try:
    ENABLE_SMS
except NameError:
    ENABLE_SMS = True

try:
    ENABLE_WHATSAPP
except NameError:
    ENABLE_WHATSAPP = True

try:
    MAX_CONTENT_LENGTH
except NameError:
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 Mo
# ===========================================================================

# --- App principale ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # Render est en HTTPS
app.config['PREFERRED_URL_SCHEME'] = 'https'  # URLs absolues en https
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)  # X-Forwarded-Proto/Host

# ✅ Aligne admin & front sur le même dossier d’upload d’images
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)

# Taille max d'upload
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Crée le dossier d'upload si besoin
try:
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)

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

# --- Admin en Blueprint (UNE SEULE FOIS) ---
from admin_server import admin_bp
app.register_blueprint(admin_bp, url_prefix='/admin')

# --- User loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== [TIGHRI_R1:MINI_MIGRATIONS_SAFE] =====================================
with app.app_context():
    db.create_all()
    try:
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
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes: {e}")

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

# ===== [TIGHRI_R1:IMAGES_INLINE_FALLBACK] ===================================
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

    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))

    img_square = ImageOps.fit(img_no_exif, TARGET_SIZE, Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = UPLOAD_FOLDER / out_name
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)

    return out_name
# ===========================================================================

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

# ======================
# Pages publiques
# ======================
@app.route('/', endpoint='index')
def index():
    featured_professionals = Professional.query.limit(6).all()
    return render_template('index.html', professionals=featured_professionals)

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

# ... (le reste de tes routes: register, login, etc. — inchangées) ...

# ===== Proxy d’images pour photos de profils =====
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"

@app.route("/media/profile/<int:professional_id>", endpoint='profile_photo')
def profile_photo(professional_id):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

    if raw_url.startswith("/media/profiles/"):
        fname = raw_url.split("/media/profiles/")[-1]
        return redirect(url_for('profile_media', filename=fname, _external=True, _scheme='https'))

    if not raw_url:
        return redirect(PHOTO_PLACEHOLDER)

    if raw_url.startswith("http://"):
        raw_url = "https://" + raw_url[len("http://"):]

    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        return redirect(PHOTO_PLACEHOLDER)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TighriBot/1.0; +https://www.tighri.com)",
        "Referer": "https://www.tighri.com",
    }
    try:
        r = requests.get(raw_url, headers=headers, timeout=8, stream=True)
        r.raise_for_status()
    except Exception:
        return redirect(PHOTO_PLACEHOLDER)

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
        return redirect(PHOTO_PLACEHOLDER)
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# Pas de bloc __main__ (gunicorn utilise app:app)
