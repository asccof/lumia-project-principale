from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy import or_, text
from jinja2 import TemplateNotFound
import os, re
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# === [TIGHRI_R1:CONFIG_INLINE_SAFE] =========================================
from pathlib import Path
import uuid, io
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

ALLOWED_SOCIAL_PLATFORMS = {'facebook', 'instagram', 'tiktok', 'youtube', 'other'}
# ===========================================================================

# --- App principale ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # Render est en HTTPS
# Taille max d'upload (respecte la valeur si déjà définie ailleurs)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Crée le dossier d'upload si besoin (idempotent)
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
from models import db, User, Professional, Appointment

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

# ======================
# Modèles complémentaires (disponibilités/indispos)
# ======================
class ProfessionalAvailability(db.Model):
    __tablename__ = "professional_availabilities"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0..6
    start_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)    # "HH:MM"
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class UnavailableSlot(db.Model):
    __tablename__ = "unavailable_slots"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# ======================
# Nouveaux modèles : Liens Sociaux & Avis
# ======================
class SocialLink(db.Model):
    __tablename__ = "social_links"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    platform = db.Column(db.String(30), nullable=False)  # facebook/instagram/tiktok/youtube/other
    url = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending/approved/rejected
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # backref : professional.social_links
    professional = db.relationship('Professional', backref=db.backref('social_links', lazy='dynamic'))

class Review(db.Model):
    __tablename__ = "reviews"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending/approved/rejected
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship('Professional', backref=db.backref('reviews', lazy='dynamic'))
    user = db.relationship('User', backref=db.backref('reviews', lazy='dynamic'))

# --- User loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== [TIGHRI_R1:MINI_MIGRATIONS_SAFE] =====================================
# Ajoute colonnes côté DB si absentes (sans casser le modèle Python)
with app.app_context():
    db.create_all()
    try:
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS address VARCHAR(255);"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;"))
        db.session.execute(text("ALTER TABLE professionals ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;"))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration adresses: {e}")

    # Seed admin si absent
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@tighri.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    u = User.query.filter_by(username=admin_username).first()
    if not u:
        u = User(
            username=admin_username,
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            is_admin=True,
            user_type="professional",
        )
        db.session.add(u)
        db.session.commit()
        app.logger.info(f"Admin '{admin_username}' créé.")
# ===========================================================================

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
# Enregistrement tolérant du pack R1 (blueprints additionnels si présents)
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
# Helpers Social/Reviews
# ======================
_url_re = re.compile(r'^(https?://)?', re.IGNORECASE)

def _normalize_url(u: str) -> str:
    u = (u or '').strip()
    if not u:
        return u
    if not _url_re.match(u):
        u = 'https://' + u
    return u

def _require_admin():
    if not (current_user.is_authenticated and getattr(current_user, 'is_admin', False)):
        flash("Accès admin requis.", "danger")
        return False
    return True

# ======================
# Pages publiques
# ======================
@app.route('/')
def index():
    featured_professionals = Professional.query.limit(6).all()
    return render_template('index.html', professionals=featured_professionals)

@app.route('/professionals')
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

@app.route('/professional/<int:professional_id>')
def professional_detail(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    return render_template('professional_detail.html', professional=professional)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

# ======================
# Authentification & Comptes
# ======================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        phone = request.form.get('phone', '').strip()

        if not username or not email or not password:
            flash("Tous les champs sont obligatoires.")
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
            user_type='patient'
        )
        if hasattr(User, 'phone') and phone:
            try:
                user.phone = phone
            except Exception:
                pass

        db.session.add(user)
        db.session.commit()

        flash('Compte patient créé avec succès!')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/professional_register', methods=['GET', 'POST'])
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

        try:
            experience = int(experience_raw or 0)
        except ValueError:
            experience = 0

        try:
            consultation_fee = float(fee_raw or 0)
        except ValueError:
            consultation_fee = 0.0

        if not username or not email or not password:
            flash("Tous les champs obligatoires ne sont pas remplis.")
            return redirect(url_for('professional_register'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('professional_register'))

        if User.query.filter_by(email=email).first():
            flash('Email déjà enregistré')
            return redirect(url_for('professional_register'))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type='professional'
        )
        if hasattr(User, 'phone') and phone:
            try:
                user.phone = phone
            except Exception:
                pass

        db.session.add(user)
        db.session.commit()

        professional = Professional(
            name=username,
            description=description or "Profil en cours de complétion.",
            specialty=specialty or "Psychologue",
            location=city or "Casablanca",
            experience_years=experience,
            consultation_fee=consultation_fee,
            status='en_attente'
        )
        db.session.add(professional)
        db.session.commit()

        flash('Compte professionnel créé avec succès! Un administrateur validera votre profil.')
        return redirect(url_for('login'))

    return render_template('professional_register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username_or_email = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter(
            or_(User.username == username_or_email, User.email == username_or_email.lower())
        ).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.user_type == 'professional':
                flash('Bienvenue dans votre espace professionnel!')
                return redirect(url_for('professional_dashboard'))
            else:
                flash('Connexion réussie!')
                return redirect(url_for('index'))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ===== [TIGHRI_R1:AUTH_PASSWORD_ROUTES] =====================================
@app.route('/change_password', methods=['GET', 'POST'])
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

@app.route('/forgot_password', methods=['GET', 'POST'])
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
@app.route('/professional_dashboard')
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

# --- EDIT PROFIL PRO: adresse / lat / lng ---
@app.route('/professional/profile', methods=['GET', 'POST'])
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
        # Conserver 'location'
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

        db.session.commit()
        flash("Profil mis à jour avec succès!")
        return redirect(url_for('professional_dashboard'))

    return render_template('professional_edit_profile.html', professional=pro)

# ===== [TIGHRI_R1:PROFILE_PHOTO_UPLOAD] =====================================
# Route média pour servir les photos locales
@app.route('/media/profiles/<path:filename>')
def profile_media(filename):
    return send_from_directory(str(UPLOAD_FOLDER), filename, as_attachment=False, max_age=31536000)

# Upload de photo de profil (fichier, pas lien)
@app.route('/professional/profile/photo', methods=['GET', 'POST'])
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
        except RuntimeError as e:
            app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow. Merci d'installer la dépendance.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")
            return redirect(url_for('professional_upload_photo'))

    return render_template('upload_photo.html')
# ===========================================================================

@app.route('/professional/availability', methods=['GET', 'POST'])
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

        for day in range(7):
            start_time = request.form.get(f'start_time_{day}', '').strip()
            end_time = request.form.get(f'end_time_{day}', '').strip()
            is_available = request.form.get(f'available_{day}') == 'on'

            if is_available and start_time and end_time:
                av = ProfessionalAvailability(
                    professional_id=professional.id,
                    day_of_week=day,
                    start_time=start_time,
                    end_time=end_time,
                    is_available=True
                )
                db.session.add(av)

        db.session.commit()
        flash('Disponibilités mises à jour avec succès!')
        return redirect(url_for('professional_availability'))

    availabilities = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    availability_dict = {av.day_of_week: av for av in availabilities}

    return render_template('professional_availability.html',
                           professional=professional,
                           availabilities=availability_dict)

@app.route('/professional/unavailable-slots', methods=['GET', 'POST'])
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

@app.route('/professional/unavailable-slots/<int:slot_id>/delete', methods=['POST'])
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

@app.route('/professional/appointments')
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
    """
    Stub de notifications (compte + téléphone).
    kind: 'accepted' | 'refused' | 'reminder' | 'pending'
    """
    app.logger.info("[NOTIFY] user=%s kind=%s ap_id=%s brand=%s",
                    user_id, kind, getattr(ap, 'id', None), BRAND_NAME)
# ===========================================================================

@app.route('/professional/appointment/<int:appointment_id>/<action>', methods=['POST'])
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
# Gestion des LIENS SOCIAUX (Pro + Admin)
# ======================
@app.route('/pro/social', methods=['GET', 'POST'])
@login_required
def pro_social():
    if current_user.user_type != 'professional':
        flash("Accès réservé aux professionnels.", "danger")
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first_or_404()

    if request.method == 'POST':
        platform = (request.form.get('platform') or '').strip().lower()
        url = _normalize_url(request.form.get('url') or '')
        if platform not in ALLOWED_SOCIAL_PLATFORMS:
            flash("Plateforme non prise en charge.", "danger")
            return redirect(url_for('pro_social'))
        if not url or len(url) < 8:
            flash("URL invalide.", "danger")
            return redirect(url_for('pro_social'))

        sl = SocialLink(professional_id=pro.id, platform=platform, url=url, status='pending')
        db.session.add(sl)
        db.session.commit()
        flash("Lien ajouté et en attente de validation.", "success")
        return redirect(url_for('pro_social'))

    links = SocialLink.query.filter_by(professional_id=pro.id).order_by(SocialLink.created_at.desc()).all()
    # Rendu template + fallback
    try:
        return render_template('pro_social_links.html', professional=pro, links=links, allowed=sorted(ALLOWED_SOCIAL_PLATFORMS))
    except TemplateNotFound:
        html = ["<h2>Mes liens sociaux</h2>",
                "<form method='post'>",
                "<select name='platform'>"] + \
               [f"<option value='{p}'>{p.capitalize()}</option>" for p in sorted(ALLOWED_SOCIAL_PLATFORMS)] + \
               ["</select> <input name='url' placeholder='https://...'>",
                "<button type='submit'>Ajouter</button>",
                "</form>",
                "<ul>"]
        for l in links:
            html.append(f"<li>{l.platform}: <a href='{l.url}' target='_blank'>{l.url}</a> — statut: {l.status} "
                        f"<form method='post' action='/pro/social/{l.id}/delete' style='display:inline'>"
                        f"<button>Supprimer</button></form></li>")
        html.append("</ul>")
        return "".join(html)

@app.route('/pro/social/<int:link_id>/delete', methods=['POST'])
@login_required
def pro_social_delete(link_id):
    if current_user.user_type != 'professional':
        flash("Accès réservé aux professionnels.", "danger")
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first_or_404()
    link = SocialLink.query.get_or_404(link_id)
    if link.professional_id != pro.id:
        flash("Action non autorisée.", "danger")
        return redirect(url_for('pro_social'))

    db.session.delete(link)
    db.session.commit()
    flash("Lien supprimé.", "success")
    return redirect(url_for('pro_social'))

@app.route('/admin/social-pending')
@login_required
def admin_social_pending():
    if not _require_admin():
        return redirect(url_for('index'))
    links = SocialLink.query.filter_by(status='pending').order_by(SocialLink.created_at.asc()).all()
    try:
        return render_template('admin_social_pending.html', links=links)
    except TemplateNotFound:
        items = "".join([f"<li>{l.platform} — <a href='{l.url}' target='_blank'>{l.url}</a> (pro #{l.professional_id}) "
                         f"<form style='display:inline' method='post' action='/admin/social/{l.id}/approve'><button>Approuver</button></form> "
                         f"<form style='display:inline' method='post' action='/admin/social/{l.id}/reject'><button>Rejeter</button></form>"
                         f"</li>" for l in links])
        return f"<h2>Liens sociaux en attente</h2><ul>{items or '<li>Aucun</li>'}</ul>"

@app.route('/admin/social/<int:link_id>/<action>', methods=['POST'])
@login_required
def admin_social_action(link_id, action):
    if not _require_admin():
        return redirect(url_for('index'))
    link = SocialLink.query.get_or_404(link_id)
    if action not in ('approve', 'reject'):
        flash("Action invalide.", "danger")
        return redirect(url_for('admin_social_pending'))
    link.status = 'approved' if action == 'approve' else 'rejected'
    db.session.commit()
    flash("Décision enregistrée.", "success")
    return redirect(url_for('admin_social_pending'))

# ======================
# Avis (Reviews)
# ======================
@app.route('/reviews/add', methods=['POST'])
@login_required
def reviews_add():
    if current_user.user_type != 'patient':
        flash("Seuls les patients peuvent déposer un avis.", "danger")
        return redirect(url_for('index'))

    pro_id = request.form.get('pro_id')
    rating = request.form.get('rating')
    comment = (request.form.get('comment') or '').strip()

    try:
        pro_id = int(pro_id)
    except Exception:
        flash("Professionnel invalide.", "danger")
        return redirect(url_for('index'))

    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            raise ValueError
    except Exception:
        flash("Note invalide (1 à 5).", "danger")
        return redirect(url_for('professional_detail', professional_id=pro_id))

    pro = Professional.query.get_or_404(pro_id)

    rv = Review(professional_id=pro.id, user_id=current_user.id, rating=rating, comment=comment, status='pending')
    db.session.add(rv)
    db.session.commit()
    flash("Merci pour votre avis ! Il sera publié après validation.", "success")
    return redirect(url_for('professional_detail', professional_id=pro.id))

@app.route('/admin/reviews-pending')
@login_required
def admin_reviews_pending():
    if not _require_admin():
        return redirect(url_for('index'))
    reviews = Review.query.filter_by(status='pending').order_by(Review.created_at.asc()).all()
    try:
        return render_template('admin_reviews_pending.html', reviews=reviews)
    except TemplateNotFound:
        def stars(n): return "★"*n + "☆"*(5-n)
        items = "".join([f"<li>Pro #{r.professional_id} — {stars(r.rating)} — {r.comment or ''} "
                         f"<form style='display:inline' method='post' action='/admin/review/{r.id}/approve'><button>Approuver</button></form> "
                         f"<form style='display:inline' method='post' action='/admin/review/{r.id}/reject'><button>Rejeter</button></form></li>"
                         for r in reviews])
        return f"<h2>Avis en attente</h2><ul>{items or '<li>Aucun</li>'}</ul>"

@app.route('/admin/review/<int:rid>/<action>', methods=['POST'])
@login_required
def admin_review_action(rid, action):
    if not _require_admin():
        return redirect(url_for('index'))
    rv = Review.query.get_or_404(rid)
    if action not in ('approve', 'reject'):
        flash("Action invalide.", "danger")
        return redirect(url_for('admin_reviews_pending'))
    rv.status = 'approved' if action == 'approve' else 'rejected'
    db.session.commit()
    flash("Décision enregistrée.", "success")
    return redirect(url_for('admin_reviews_pending'))

# ======================
# API REST
# ======================
@app.route('/api/professionals')
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
        'longitude': getattr(p, 'longitude', None)
    } for p in pros])

@app.route('/api/professional/<int:professional_id>/available-slots')
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

    slots = []
    for availability in availabilities:
        start_time = datetime.strptime(availability.start_time, '%H:%M').time()
        end_time = datetime.strptime(availability.end_time, '%H:%M').time()

        current = start_time
        while current < end_time:
            slot_start = current
            slot_end = (datetime.combine(date.today(), current) + timedelta(minutes=30)).time()

            is_unavailable = any(
                (slot_start >= datetime.strptime(u.start_time, '%H:%M').time()
                 and slot_start < datetime.strptime(u.end_time, '%H:%M').time())
                for u in unavailable_slots
            )

            is_booked = any(
                slot_start <= a.appointment_date.time() < slot_end
                for a in confirmed
            )

            if not is_unavailable and not is_booked:
                slots.append({
                    'start_time': slot_start.strftime('%H:%M'),
                    'end_time': slot_end.strftime('%H:%M'),
                    'available': True
                })

            current = slot_end

    return jsonify({
        'professional_id': professional_id,
        'date': target_date.isoformat(),
        'available_slots': slots
    })

# ======================
# Réservation & Mes RDV
# ======================
@app.route('/book_appointment/<int:professional_id>', methods=['GET', 'POST'])
@login_required
def book_appointment(professional_id):
    professional = Professional.query.get_or_404(professional_id)

    if professional.status != 'valide':
        flash("Ce professionnel n'est pas encore validé par l'administration.")
        return redirect(url_for('professionals'))

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

        # Vérifier disponibilités
        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id,
            day_of_week=day_of_week,
            is_available=True
        ).all()

        if not any(av.start_time <= appointment_time <= av.end_time for av in availabilities):
            flash("Cette heure n'est pas disponible pour ce professionnel.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Déjà réservé ?
        existing = Appointment.query.filter_by(
            professional_id=professional_id,
            appointment_date=appointment_datetime,
            status='confirme'
        ).first()
        if existing:
            flash("Ce créneau est déjà réservé.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Indisponibilités ?
        slots = UnavailableSlot.query.filter_by(
            professional_id=professional_id,
            date=appointment_date_obj
        ).all()
        if any(s.start_time <= appointment_time <= s.end_time for s in slots):
            flash("Ce créneau est marqué comme indisponible.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Créer RDV (statut EN ATTENTE)
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

    # Affichage
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

@app.route('/my_appointments')
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
@app.get('/cron/send-reminders-24h')
def cron_send_reminders_24h():
    """
    Endpoint de cron sécurisé (Render/worker) :
    appeler /cron/send-reminders-24h?token=XXX
    où XXX = os.environ['CRON_TOKEN'].
    """
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
# ===========================================================================

# ======================
# Site Status
# ======================
@app.route('/site-status')
def site_status():
    status = app.config.get('SITE_STATUS', {})
    stats = {
        'total_professionals': Professional.query.count(),
        'total_users': User.query.count(),
        'total_appointments': Appointment.query.count(),
        'database_file': 'tighri.db',  # compat UI
        'server_port': 5000,
        'admin_port': 8080
    }
    return render_template('site_status.html', status=status, stats=stats)

# Pas de bloc __main__ pour Render (gunicorn utilise app:app)
