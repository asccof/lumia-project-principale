from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response
)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
    # noqa
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
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from notifications import send_email, send_sms, send_whatsapp
from admin_server import _build_notif  # on réutilise les mêmes textes d’emails que l’admin
# --- Email wrapper (app.py) -----------------------------------------------
from flask import current_app
from notifications import send_email as _notif_send_email  # lit vos MAIL_* sur Render

def safe_send_email(to_addr: str, subject: str, body_text: str, html: str | None = None) -> bool:
    """
    Wrapper unique appelé par les routes.
    - Ne casse jamais la requête (try/except).
    - Délègue l'envoi réel à notifications.py qui utilise MAIL_* (Zoho).
    """
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
# --------------------------------------------------------------------------

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

# NEW: racine persistante des uploads (monte un Render Disk et mets UPLOAD_ROOT=/var/data/uploads)
try:
    UPLOAD_ROOT
except NameError:
    UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))

try:
    UPLOAD_FOLDER
except NameError:
    # Les photos de profil seront dans <UPLOAD_ROOT>/profiles
    UPLOAD_FOLDER = Path(UPLOAD_ROOT) / 'profiles'

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
app.config['PREFERRED_URL_SCHEME'] = 'https'

# --- Cookies "remember me" (Flask-Login) ---
app.config["REMEMBER_COOKIE_NAME"] = "tighri_remember"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=60)
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Dossier d’upload des images de profils
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Crée le dossier si besoin (racine + profiles)
try:
    Path(UPLOAD_ROOT).mkdir(parents=True, exist_ok=True)
    Path(UPLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)

# --- OAuth (Google) configuration ---
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v3/",
    client_kwargs={
        "scope": "openid email profile",
        "prompt": "select_account",
    },
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
from admin_server import admin_bp, ProfessionalOrder  # <— NOTE: on importe aussi la classe de classement
app.register_blueprint(admin_bp, url_prefix='/admin')

# --- User loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== [TIGHRI_R1:MINI_MIGRATIONS_SAFE] =====================================
with app.app_context():
    # create_all va aussi créer la table 'professional_order' car ProfessionalOrder est importé ci-dessus
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
        # Durée & buffer par défaut
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER DEFAULT 45;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS buffer_between_appointments_minutes INTEGER DEFAULT 15;"))

        # users: téléphone
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"))
        # users: oauth (si tu n'as pas fait la migration, on les ajoute à chaud)
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;"))
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);"))
        # index utile sur oauth_sub
        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);"))

        # --- Jetons de reset de mot de passe (usage unique + expiration 24h)
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

# ===== Helpers reset mot de passe (token signé + hash DB) ====================
def _password_reset_ts():
    # Jeton signé (défense en profondeur en plus du jeton DB)
    return URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="tighri-password-reset")

def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()

def issue_reset_token(user, hours=24) -> str:
    """Crée un jeton de reset à usage unique, valable X heures, et le stocke en DB (hash)."""
    tok = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(tok)
    user.reset_token_expires_at = datetime.utcnow() + timedelta(hours=hours)
    db.session.commit()
    return tok

def consume_token_to_user(token: str):
    """Vérifie le jeton (hash + expiration). Ne l’invalide pas encore (fait après succès)."""
    if not token:
        return None
    h = _hash_token(token)
    u = User.query.filter_by(reset_token_hash=h).first()
    if not u:
        return None
    if not u.reset_token_expires_at or u.reset_token_expires_at < datetime.utcnow():
        return None
    return u
# ============================================================================

# ===== [TIGHRI_R1:IMAGES_INLINE_FALLBACK] ===================================
TARGET_SIZE = (512, 512)

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _process_and_save_profile_image(file_storage) -> str:
    """
    Traite l'image de profil (vérif + carré 512 + JPEG qualité) et sauvegarde.
    Retourne le nom de fichier (ex: 'a1b2c3.jpg').
    """
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

# ===== [TIGHRI_R1:PACK_REGISTRATION_SAFE] ===================================
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
    """
    Accueil : affiche 6 pros en respectant le classement admin (professional_order.order_priority ASC),
    puis des tiebreakers stables. Fallback sûr si la table d'ordre n'existe pas encore.
    """
    try:
        # tri principal : ordre admin, puis featured, puis featured_rank, puis récents
        featured_professionals = (
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
            .limit(6)
            .all()
        )
    except Exception as e:
        # En cas d'erreur (ex: table non présente), on ne casse pas l'accueil
        app.logger.warning("Classement admin indisponible (%s), fallback 'featured puis récents'.", e)
        featured_professionals = (
            Professional.query
            .filter_by(status='valide')
            .order_by(Professional.is_featured.desc(), Professional.created_at.desc(), Professional.id.desc())
            .limit(6)
            .all()
        )

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
        except Exception as e:
            from sqlalchemy.exc import IntegrityError, DataError
            db.session.rollback()
            app.logger.exception("PRO_REGISTER_FAIL for username=%s email=%s: %s", username, email, e)
            if isinstance(e, IntegrityError):
                msg = str(getattr(e, "orig", e)).lower()
                if "username" in msg:
                    flash("Nom d’utilisateur déjà pris. Merci d’en choisir un autre.", "danger")
                elif "email" in msg:
                    flash("Email déjà enregistré. Utilisez une autre adresse ou connectez-vous.", "danger")
                else:
                    flash("Contrainte de base de données. Vérifiez que l’email/nom ne sont pas déjà utilisés.", "danger")
            elif isinstance(e, DataError):
                flash("Données trop longues ou caractères non pris en charge (évitez les emojis).", "danger")
            else:
                flash("Erreur lors de la création du compte professionnel. Vérifiez vos champs et réessayez.", "danger")
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
            # IMPORTANT: cookie persistant 60 jours si remember coché
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

        # Lier par oauth_sub OU par email existant
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
            # Création d'un nouveau compte (mot de passe local non requis)
            username_base = email.split("@")[0]
            username = username_base
            # garantie unicité username
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
                user_type="professional"  # adapte si tu veux une autre valeur par défaut
            )
            db.session.add(user)
            db.session.commit()

        login_user(user, remember=True, duration=timedelta(days=60))
        flash("Connexion via Google réussie ✅", "success")
        # redirection selon le type d'utilisateur
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
            # Compte social: on autorise de définir un mot de passe local (old doit rester vide)
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
        email = (request.form.get('email','') or '').strip().lower()

        # Réponse neutre (ne pas divulguer l’existence d’un compte)
        flash('Si le compte existe, un email de réinitialisation a été envoyé.', 'info')

        if not email:
            return redirect(url_for('login'))

        user = User.query.filter_by(email=email).first()
        if not user:
            return redirect(url_for('login'))

        try:
            # 1) Jeton DB à usage unique + 2) jeton signé (défense en profondeur)
            tok = issue_reset_token(user, hours=24)
            ts = _password_reset_ts()
            signed = ts.dumps({"uid": user.id, "t": tok})

            reset_url = url_for('reset_password', token=signed, _external=True, _scheme='https')
            subject = "Réinitialisation de votre mot de passe Tighri"
            body = (
                "Bonjour,\n\n"
                "Pour réinitialiser votre mot de passe Tighri, cliquez sur le lien ci-dessous :\n"
                f"{reset_url}\n\n"
                "Ce lien expire dans 24 heures. Si vous n’êtes pas à l’origine de cette demande, ignorez cet email.\n\n"
                "— L’équipe Tighri"
            )
            safe_send_email(user.email, subject, body)
        except Exception as e:
            app.logger.warning("Forgot password: send failed for %s: %s", email, e)

        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'], endpoint='reset_password')
def reset_password(token):
    ts = _password_reset_ts()
    try:
        data = ts.loads(token, max_age=60*60*24)  # 24h
        uid = int(data.get("uid"))
        raw_tok = data.get("t") or ""
    except (BadSignature, SignatureExpired, ValueError):
        flash("Lien de réinitialisation invalide ou expiré. Refaites une demande.", "danger")
        return redirect(url_for('forgot_password'))

    # Vérifie le token DB (usage unique + expiration)
    user = consume_token_to_user(raw_tok)
    if not user or user.id != uid:
        flash("Lien de réinitialisation invalide ou expiré. Refaites une demande.", "danger")
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

        try:
            user.password_hash = generate_password_hash(new)
            # Invalider immédiatement le jeton (usage unique)
            user.reset_token_hash = None
            user.reset_token_expires_at = None
            db.session.commit()
            flash("Mot de passe réinitialisé. Vous pouvez vous connecter.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.exception("Reset password commit failed for uid=%s: %s", uid, e)
            flash("Erreur interne. Réessayez.", "danger")
            return redirect(url_for('reset_password', token=token))

    return render_template('reset_password.html', user=user)
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

        # ✅ Téléphone
        pro.phone = ((request.form.get('phone') or '').strip() or None)

        # ✅ Prix (MAD)
        fee_raw = (request.form.get('consultation_fee') or '').replace(',', '.').strip()
        if fee_raw != '':
            try:
                pro.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Tarif invalide (MAD).", "error")

        # ✅ Types de consultation
        types_list = request.form.getlist('consultation_types')  # ex: ['cabinet','en_ligne']
        if types_list:
            allowed = ['cabinet', 'domicile', 'en_ligne']
            cleaned = [t for t in allowed if t in set(types_list)]
            if cleaned:
                pro.consultation_types = ','.join(cleaned)

        # ✅ Liens sociaux (dés-approbation auto si modifiés)
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
            # Toute modif repasse en attente d’approbation admin
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
    """Retourne l'avatar par défaut si présent dans static, sinon un placeholder neutre."""
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        # Cache 1 jour
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    # Sinon placeholder externe (évite 404)
    return redirect(PHOTO_PLACEHOLDER)

# ===== Photos de profil =====
@app.route('/media/profiles/<path:filename>', endpoint='profile_media')
def profile_media(filename):
    """
    Sert un fichier de profil depuis le stockage persistant.
    Si absent → avatar par défaut (au lieu d'un 404).
    """
    # sécurise le path
    safe_name = os.path.basename(filename)
    file_path = Path(UPLOAD_FOLDER) / safe_name
    if file_path.exists() and file_path.is_file():
        resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=31536000"
        return resp
    # fallback propre (évite les 404 observés dans les logs)
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

@app.route('/professional/appointments', endpoint='professional_appointments')
@login_required
def professional_appointments():
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
    return render_template('professional_appointments.html',
                           professional=professional,
                           appointments=appointments)

# ===== [EMAIL GUARD] ========================================================
def email_config_ok() -> bool:
    """
    Accepte EMAIL_* (prioritaire) ou MAIL_* (fallback).
    """
    enabled = (os.getenv("EMAIL_ENABLED") or os.getenv("MAIL_ENABLED") or "true").strip().lower() == "true"

    host   = os.getenv("EMAIL_HOST") or os.getenv("MAIL_SERVER")
    port   = os.getenv("EMAIL_PORT") or os.getenv("MAIL_PORT")
    user   = os.getenv("EMAIL_USER") or os.getenv("MAIL_USERNAME")
    pw     = os.getenv("EMAIL_PASS") or os.getenv("MAIL_PASSWORD")
    sender = os.getenv("EMAIL_FROM") or os.getenv("MAIL_DEFAULT_SENDER") or user

    missing = [k for k, v in [("host", host), ("user", user), ("password", pw), ("from", sender)] if not v]
    if missing or not enabled:
        app.logger.warning("[NOTIF][EMAIL] Config incomplète (enabled=%s) ; manquants=%s", enabled, missing)
        return False
    return True
# ===========================================================================

# ===== [TIGHRI_R1:NOTIFY_STUB] ==============================================
def notify_user_account_and_phone(user_id: int, kind: str, ap: Appointment):
    """
    Envoie les notifications e-mail :
    - au patient (si e-mail dispo)
    - au professionnel UNIQUEMENT quand kind == 'pending' (nouvelle demande)
    """
    # Patient
    try:
        user = User.query.get(user_id)  # patient
    except Exception:
        user = None

    try:
        if user and getattr(user, 'email', None):
            subject, text = _build_notif(kind, ap, role='patient')
            safe_send_email(user.email, subject, text)
    except Exception as e:
        app.logger.warning("Notify patient email failed: %s", e)

    # Pro (uniquement à la création 'pending')
    if kind == 'pending':
        try:
            pro = ap.professional or Professional.query.get(ap.professional_id)
        except Exception:
            pro = None

        pro_email = None
        if pro:
            try:
                pro_user = User.query.filter_by(username=pro.name).first()
            except Exception:
                pro_user = None
            pro_email = getattr(pro_user, 'email', None) if pro_user else None

        if pro_email:
            try:
                subject, text = _build_notif('pending', ap, role='pro')
                safe_send_email(pro_email, subject, text)
            except Exception as e:
                app.logger.warning("Notify pro email failed: %s", e)

    # SMS / WhatsApp restent des stubs pour l’instant (non activés)
    app.logger.info("[NOTIFY] kind=%s ap_id=%s done", kind, getattr(ap, 'id', None))

# ===========================================================================

@app.route('/professional/appointment/<int:appointment_id>/<action>', methods=['POST'], endpoint='professional_appointment_action'])
@login_required
def professional_appointment_action(appointment_id, action):
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))

    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.professional_id != professional.id:
        flash('Accès non autorisé')
        return redirect(url_for('professional_appointments'))

    duration = int(getattr(professional, 'consultation_duration_minutes', 45) or 45)

    if action == 'accept':
        appointment.status = 'confirme'
        db.session.commit()
        notify_user_account_and_phone(user_id=appointment.patient_id, kind='accepted', ap=appointment)
        flash('Rendez-vous accepté!')
    elif action == 'reject':
        appointment.status = 'annule'
        db.session.commit()
        notify_user_account_and_phone(user_id=appointment.patient_id, kind='refused', ap=appointment)
        flash('Rendez-vous refusé!')

    return redirect(url_for('professional_appointments'))

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

        notify_user_account_and_phone(user_id=current_user.id, kind='pending', ap=appointment)

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

# ===== [TIGHRI_R1:CRON_REMINDER] ============================================
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
        notify_user_account_and_phone(user_id=ap.patient_id, kind='reminder', ap=ap)

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
        # si le fichier local n'existe pas, on renverra le fallback via profile_media
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

# ===== Favicon (évite le 404 vu dans les logs) ==============================
@app.route("/favicon.ico")
def favicon():
    # essaie de servir static/favicon.ico, sinon rien (204) pour éviter 404
    fav_path = Path(app.static_folder or (BASE_DIR / "static")) / "favicon.ico"
    if fav_path.exists():
        resp = send_from_directory(app.static_folder, "favicon.ico", conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp
    return ("", 204)

# Pas de bloc __main__ (gunicorn utilise app:app)
