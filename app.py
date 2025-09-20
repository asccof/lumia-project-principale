# app.py
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response, current_app, g, session, make_response
)
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, date, timedelta, time as dtime
from sqlalchemy import or_, text, and_
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

# Racine persistante des uploads
UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = Path(UPLOAD_ROOT) / 'profiles'
ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif'}
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")
ENABLE_SMS = (os.getenv("ENABLE_SMS", "true").lower() == "true")
ENABLE_WHATSAPP = (os.getenv("ENABLE_WHATSAPP", "true").lower() == "true")
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo
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

# Dossier d’upload
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Crée les dossiers si besoin
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
    client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
)

# --- Normalisation URI Postgres -> psycopg3 ---
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

# --- Config DB + modèles ---
from models import (
    db, User, Professional, Appointment,
    ProfessionalAvailability, UnavailableSlot,
    City, Specialty, professional_specialties
)
from admin_server import admin_bp, ProfessionalOrder, _build_notif  # BP admin + helpers

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

# ===== Langue (Phase 1) =====================================================
@app.before_request
def _set_lang():
    lang = session.get("lang") or request.cookies.get("lang") or "fr"
    g.current_locale = lang
    g.current_locale_label = {"fr": "Français", "ar": "العربية", "en": "English"}.get(lang, "Français")

@app.route("/set-language/<lang>")
def set_language(lang):
    if lang not in ("fr", "ar", "en"):
        lang = "fr"
    session["lang"] = lang
    resp = make_response(redirect(request.referrer or url_for("index")))
    resp.set_cookie("lang", lang, max_age=60*60*24*365)
    return resp
# ===========================================================================

# ===== Mini-migrations sûres ===============================================
with app.app_context():
    db.create_all()
    try:
        # Ajouts sur professionals (idempotents)
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

        # Phase 1 : colonnes normalisées + badges
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS city_id INTEGER;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS primary_specialty_id INTEGER;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS certified_tighri BOOLEAN DEFAULT FALSE;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS approved_anthecc BOOLEAN DEFAULT FALSE;"))
        # FK soft (si supporté)
        db.session.execute(text("""
            DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'fk_prof_city'
            ) THEN
                ALTER TABLE professionals
                ADD CONSTRAINT fk_prof_city FOREIGN KEY (city_id) REFERENCES cities(id) ON DELETE SET NULL;
            END IF;
            END $$;
        """))
        db.session.execute(text("""
            DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'fk_prof_primary_spec'
            ) THEN
                ALTER TABLE professionals
                ADD CONSTRAINT fk_prof_primary_spec FOREIGN KEY (primary_specialty_id) REFERENCES specialties(id) ON DELETE SET NULL;
            END IF;
            END $$;
        """))

        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes Phase1: {e}")

    # Seed admin si absent (inchangé)
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

# ===== Helpers reset mot de passe ==========================================
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

# ===== Images profils =======================================================
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

# ===== Pack optionnel (inchangé) ===========================================
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
    Accueil avec mise en avant + référentiels normalisés.
    """
    # Classement tel que déjà en place (ordre admin / featured / récents)
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

    # Référentiels pour l’UI (liste déroulante si tu l’ajoutes plus tard)
    cities = City.query.order_by(City.name.asc()).all()
    specialties = Specialty.query.order_by(Specialty.name.asc()).all()

    return render_template(
        'index.html',
        top_professionals=top_professionals,
        other_professionals=more_professionals,
        cities=cities,
        specialties=specialties
    )

# Liste de pros avec filtres normalisés (compatible avec l’existant)
@app.route('/professionals', endpoint='professionals')
def professionals():
    q = (request.args.get('q') or '').strip()

    # Filtres normalisés (optionnels)
    city_id = (request.args.get('city_id') or '').strip()
    city_txt = (request.args.get('city') or '').strip()
    spec_id = (request.args.get('specialty_id') or '').strip()
    spec_txt = (request.args.get('specialty') or '').strip()
    mode = (request.args.get('mode') or '').strip().lower()  # cabinet | visio | domicile

    base_query = Professional.query.filter_by(status='valide')

    # Plein texte simple
    if q:
        like = f"%{q}%"
        conditions = [
            Professional.name.ilike(like),
            Professional.specialty.ilike(like),
            Professional.location.ilike(like),
            Professional.description.ilike(like),
        ]
        if hasattr(Professional, "address"):
            conditions.insert(2, Professional.address.ilike(like))
        base_query = base_query.filter(or_(*conditions))

    # Filtre Ville
    if city_id.isdigit():
        base_query = base_query.filter(Professional.city_id == int(city_id))
    elif city_txt:
        base_query = base_query.outerjoin(City).filter(
            or_(City.name.ilike(f"%{city_txt}%"), Professional.address.ilike(f"%{city_txt}%"))
        )

    # Filtre Spécialité
    if spec_id.isdigit():
        base_query = base_query.filter(
            or_(
                Professional.primary_specialty_id == int(spec_id),
                Professional.specialties.any(Specialty.id == int(spec_id))
            )
        )
    elif spec_txt:
        like = f"%{spec_txt}%"
        base_query = base_query.outerjoin(Professional.primary_specialty).outerjoin(Professional.specialties)
        base_query = base_query.filter(
            or_(Specialty.name.ilike(like), Professional.specialty.ilike(like))
        )

    # Filtre mode consultation
    if mode in ("cabinet", "visio", "domicile", "en_ligne"):
        key = "en_ligne" if mode in ("visio", "en_ligne") else mode
        base_query = base_query.filter(
            or_(
                Professional.consultation_types.ilike(f"%{key}%"),
                Professional.consultation_types == key
            )
        )

    pros = base_query.order_by(
        Professional.is_featured.desc(),
        db.func.coalesce(Professional.featured_rank, 999999).asc(),
        Professional.created_at.desc(),
        Professional.id.desc()
    ).all()

    # Page de liste existante / ou celle fournie
    # Si tu as déjà templates/professionals.html, on garde.
    # Sinon, remplace par "professionals_list.html".
    return render_template('professionals.html', professionals=pros, specialty=request.args.get('specialty', 'all'), search_query=q)

@app.route('/professional/<int:professional_id>', endpoint='professional_detail')
def professional_detail(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    reviews = []  # placeholder : tu pourras brancher plus tard
    return render_template('professional_detail.html', professional=professional, reviews=reviews)

@app.route('/about', endpoint='about')
def about():
    return render_template('about.html')

@app.route('/contact', endpoint='contact')
def contact():
    return render_template('contact.html')

# ===== Page ANTHECC (Phase 1) ==============================================
@app.route('/anthecc', endpoint='anthecc')
def anthecc():
    # Crée un template "anthecc.html" minimal, ou réutilise base avec contenu statique
    return render_template('anthecc.html')
# ===========================================================================

# ======================
# Authentification & Comptes (inchangé)
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
        specialty_txt = request.form.get('specialty', '').strip()
        city_txt = request.form.get('city', '').strip()
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

        # Mapper ville/specialty texte -> référentiels si présents
        city_ref = City.query.filter(City.name.ilike(city_txt)).first() if city_txt else None
        spec_ref = Specialty.query.filter(Specialty.name.ilike(specialty_txt)).first() if specialty_txt else None

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
                specialty=specialty_txt or "Psychologue",  # compat legacy
                location=city_txt or "Casablanca",        # compat legacy
                primary_specialty=spec_ref,
                city=city_ref,
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
                status='en_attente',
                certified_tighri=False,
                approved_anthecc=False
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

# ===== Password routes (inchangé) ==========================================
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
# Espace Professionnel (inchangé)
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

        # Normalisation via référentiels si fournis
        city_txt = (request.form.get('city_name') or '').strip()
        if city_txt:
            ref = City.query.filter(City.name.ilike(city_txt)).first()
            if ref:
                pro.city = ref
        spec_txt = (request.form.get('primary_specialty_name') or '').strip()
        if spec_txt:
            ref = Specialty.query.filter(Specialty.name.ilike(spec_txt)).first()
            if ref:
                pro.primary_specialty = ref

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

        # Badges (optionnel si formulaire les expose)
        if request.form.get('certified_tighri') is not None:
            pro.certified_tighri = request.form.get('certified_tighri') in ('1','true','on','yes')
        if request.form.get('approved_anthecc') is not None:
            pro.approved_anthecc = request.form.get('approved_anthecc') in ('1','true','on','yes')

        db.session.commit()
        flash("Profil mis à jour avec succès!")
        return redirect(url_for('professional_dashboard'))

    return render_template('professional_edit_profile.html', professional=pro)

# ===== Helpers d'avatar / fallback =====
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"  # à placer dans static/img/

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

# Photos proxy / media
@app.route("/media/profiles/<path:filename>", endpoint='profile_media')
def profile_media(filename):
    safe_name = os.path.basename(filename)
    file_path = Path(UPLOAD_FOLDER) / safe_name
    if file_path.exists() and file_path.is_file():
        resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=31536000"
        return resp
    return _avatar_fallback_response()

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

# Alias rétro-compatibles
@app.route("/avatar", endpoint="avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# ======================
# API dispo & RDV (inchangé)
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
        'certified_tighri': getattr(p, 'certified_tighri', False),
        'approved_anthecc': getattr(p, 'approved_anthecc', False),
        'city': (p.city.name if getattr(p, 'city', None) else None),
        'primary_specialty': (p.primary_specialty.name if getattr(p, 'primary_specialty', None) else None),
    } for p in pros])

# (… tes autres routes API RDV existantes, inchangées …)
# CRON / site-status etc. restent en place dans ton fichier original

# Entrée WSGI
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
