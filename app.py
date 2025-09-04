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
        # ✅ Durée & buffer par défaut demandés: 45 et 15
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER DEFAULT 45;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS buffer_between_appointments_minutes INTEGER DEFAULT 15;"))

        # users: téléphone
        db.session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"))

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

# ===== [TIGHRI_R1:IMAGES_INLINE_FALLBACK] ===================================
TARGET_SIZE = (512, 512)

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _process_and_save_profile_image(file_storage) -> str:
    """
    Traite l'image de profil (vérif + carré 512 + JPEG qualité) et sauvegarde dans UPLOAD_FOLDER.
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
        img.verify()  # intégrité
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # Supprimer EXIF (recréation)
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))

    img_square = ImageOps.fit(img_no_exif, TARGET_SIZE, Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = UPLOAD_FOLDER / out_name
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

        # Réseaux sociaux (présents dans le formulaire)
        facebook_url  = (request.form.get('facebook_url')  or '').strip()
        instagram_url = (request.form.get('instagram_url') or '').strip()
        tiktok_url    = (request.form.get('tiktok_url')    or '').strip()
        youtube_url   = (request.form.get('youtube_url')   or '').strip()

        # Validations basiques
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

        # ==== ATOMIQUE : création User + Professional dans une seule transaction ====
        try:
            # Créer l'utilisateur pro
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                user_type='professional',
                phone=phone
            )
            db.session.add(user)

            # Créer le profil pro correspondant
            professional = Professional(
                name=username,  # cohérence avec l'espace pro existant (name == username)
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

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember)
            if user.user_type == 'professional':
                flash('Bienvenue dans votre espace professionnel!')
                return redirect(url_for('professional_dashboard'))
            else:
                flash('Connexion réussie!')
                return redirect(url_for('index'))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")

    return render_template('login.html')

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
        old = request.form.get('old', '')
        new = request.form.get('new', '')
        if not check_password_hash(current_user.password_hash, old):
            flash('Ancien mot de passe incorrect.', 'danger')
        else:
            current_user.password_hash = generate_password_hash(new)
            db.session.commit()
            flash('Mot de passe modifié.', 'success')
            return redirect(url_for('index'))
    return render_template('change_password.html')

@app.route('/forgot_password', methods=['GET', 'POST'], endpoint='forgot_password')
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email','').strip().lower()
        # TODO: générer un token et envoyer par email (à implémenter)
        flash('Si le compte existe, un email de réinitialisation a été envoyé.', 'info')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')
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

# --- EDIT PROFIL PRO: adresse / lat / lng + durée/buffer ---
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
        # Champs textes
        pro.name = (request.form.get('name') or pro.name).strip()
        pro.specialty = (request.form.get('specialty') or pro.specialty or '').strip()
        pro.description = (request.form.get('description') or pro.description or '').strip()
        # Adresse exacte
        addr = (request.form.get('address') or '').strip()
        if hasattr(pro, "address"):
            pro.address = addr
        # Ville (fallback)
        loc = (request.form.get('location') or '').strip()
        if loc:
            pro.location = loc
        # Lat/Lng
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

        # ✅ NOUVEAU : durée & buffer (facultatif)
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

# ===== [TIGHRI_R1:PROFILE_PHOTO_UPLOAD] =====================================
# ===== Proxy d’images pour photos de profils (robuste) =====
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"

@app.route("/media/profile/<int:professional_id>", endpoint='profile_photo')
def profile_photo(professional_id):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

    # 1) Cas fichier local enregistré en DB: "/media/profiles/<fname>"
    if raw_url.startswith("/media/profiles/"):
        fname = raw_url.split("/media/profiles/")[-1].strip("/")
        local_path = UPLOAD_FOLDER / fname
        if local_path.exists():
            # Sert directement le fichier (évite 302 puis 404)
            return send_from_directory(str(UPLOAD_FOLDER), fname, as_attachment=False, max_age=31536000)
        else:
            app.logger.warning("Photo locale manquante: %s", local_path)
            return redirect(PHOTO_PLACEHOLDER)

    # 2) Pas d’image enregistrée
    if not raw_url:
        return redirect(PHOTO_PLACEHOLDER)

    # 3) URL externe : on proxifie (avec headers) et on gère les erreurs proprement
    if raw_url.startswith("http://"):
        raw_url = "https://" + raw_url[len("http://"):]
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        return redirect(PHOTO_PLACEHOLDER)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TighriBot/1.0; +https://www.tighri.com)",
        "Referer": "https://www.tighri.com",
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }
    try:
        r = requests.get(raw_url, headers=headers, timeout=8)
        if r.status_code >= 400 or not r.content:
            app.logger.info("Image externe KO (%s): %s", r.status_code, raw_url)
            return redirect(PHOTO_PLACEHOLDER)
    except Exception as e:
        app.logger.info("Erreur image externe: %s | %s", e, raw_url)
        return redirect(PHOTO_PLACEHOLDER)

    content_type = r.headers.get("Content-Type", "image/jpeg")
    resp = Response(r.content, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

# ===========================================================================

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

# ===== [TIGHRI_R1:NOTIFY_STUB] ==============================================
def notify_user_account_and_phone(user_id: int, kind: str, ap: Appointment):
    app.logger.info("[NOTIFY] user=%s kind=%s ap_id=%s brand=%s",
                    user_id, kind, getattr(ap, 'id', None), BRAND_NAME)
# ===========================================================================

@app.route('/professional/appointment/<int:appointment_id>/<action>', methods=['POST'], endpoint='professional_appointment_action')
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

# Pas de bloc __main__ (gunicorn utilise app:app)
