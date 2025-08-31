from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date, timedelta
from sqlalchemy import or_, text
import os
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
# ===========================================================================

# ===== [TIGHRI_P1:PHONE_VALIDATION_HELPERS] ==================================
PHONE_MIN_DIGITS = 9

def _digits_only(s: str) -> str:
    return ''.join(ch for ch in (s or '') if ch.isdigit())

def _is_valid_phone(raw: str) -> bool:
    """
    Validation simple : au moins 9 chiffres (ex: 0663..., 21266..., +21266...).
    On évite d'être trop strict pour accepter divers formats.
    """
    return len(_digits_only(raw)) >= PHONE_MIN_DIGITS
# ============================================================================

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

# --- User loader ---
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===== [TIGHRI_R1:MINI_MIGRATIONS_SAFE] =====================================
# Ajoute colonnes côté DB si absentes (sans casser le modèle Python)
with app.app_context():
    db.create_all()
    try:
        # Professionals : adresse + géoloc
        db.session.execute(text(
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS address VARCHAR(255);"
        ))
        db.session.execute(text(
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;"
        ))
        db.session.execute(text(
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;"
        ))
        # Users : téléphone
        db.session.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);"
        ))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migrations: {e}")

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
        # Optionnel : u.phone = "0663400190"
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
        phone = request.form.get('phone', '').strip()  # ← obligatoire

        # Validations de base
        if not username or not email or not password or not phone:
            flash("Tous les champs sont obligatoires (y compris le téléphone).", "danger")
            return redirect(url_for('register'))
        if not _is_valid_phone(phone):
            flash("Numéro de téléphone invalide. Merci de vérifier.", "danger")
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris", "danger")
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré", "danger")
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

        flash('Compte patient créé avec succès!', "success")
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
        phone = request.form.get('phone', '').strip()  # ← obligatoire

        # Validations de base
        if not username or not email or not password or not phone:
            flash("Tous les champs obligatoires ne sont pas remplis (y compris le téléphone).", "danger")
            return redirect(url_for('professional_register'))
        if not _is_valid_phone(phone):
            flash("Numéro de téléphone invalide. Merci de vérifier.", "danger")
            return redirect(url_for('professional_register'))

        try:
            experience = int(experience_raw or 0)
        except ValueError:
            experience = 0

        try:
            consultation_fee = float((fee_raw or '0').replace(',', '.'))
        except ValueError:
            consultation_fee = 0.0

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris", "danger")
            return redirect(url_for('professional_register'))
        if User.query.filter_by(email=email).first():
            flash('Email déjà enregistré', "danger")
            return redirect(url_for('professional_register'))

        # Création du user (type professional) avec téléphone
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type='professional',
            phone=phone
        )
        db.session.add(user)
        db.session.commit()

        # Création du profil pro + réplique le téléphone pour l’affichage public
        professional = Professional(
            name=username,
            description=description or "Profil en cours de complétion.",
            specialty=specialty or "Psychologue",
            location=city or "Casablanca",
            experience_years=experience,
            consultation_fee=consultation_fee,
            status='en_attente',
            phone=phone
        )
        db.session.add(professional)
        db.session.commit()

        flash('Compte professionnel créé avec succès! Un administrateur validera votre profil.', "success")
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
                flash('Bienvenue dans votre espace professionnel!', "success")
                return redirect(url_for('professional_dashboard'))
            else:
                flash('Connexion réussie!', "success")
                return redirect(url_for('index'))

        flash("Nom d'utilisateur / email ou mot de passe incorrect", "danger")

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
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
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
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé", 'danger')
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
        # Conserver 'location' pour compat/fallback
        loc = (request.form.get('location') or '').strip()
        if loc:
            pro.location = loc
        # Lat/Lng
        lat = (request.form.get('latitude') or '').strip()
        lng = (request.form.get('longitude') or '').strip()
        try:
            val_lat = float(lat) if lat else None
        except ValueError:
            flash("Latitude invalide", "danger")
            return redirect(url_for('professional_edit_profile'))
        try:
            val_lng = float(lng) if lng else None
        except ValueError:
            flash("Longitude invalide", "danger")
            return redirect(url_for('professional_edit_profile'))

        if hasattr(pro, "latitude"):
            pro.latitude = val_lat
        if hasattr(pro, "longitude"):
            pro.longitude = val_lng

        db.session.commit()
        flash("Profil mis à jour avec succès!", "success")
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
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé", 'danger')
        return redirect(url_for('professional_dashboard'))

    if request.method == 'POST':
        file = request.files.get('photo')
        if not file:
            flash("Veuillez sélectionner une image.", "warning")
            return redirect(url_for('professional_upload_photo'))
        try:
            saved_name = _process_and_save_profile_image(file)
            # Conserver compatibilité : on stocke l'URL locale dans image_url
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
# ===========================================================================

@app.route('/professional/availability', methods=['GET', 'POST'])
@login_required
def professional_availability():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
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
        flash('Disponibilités mises à jour avec succès!', "success")
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
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
        return redirect(url_for('index'))

    if request.method == 'POST':
        date_str = request.form.get('date', '')
        start_time = request.form.get('start_time', '')
        end_time = request.form.get('end_time', '')
        reason = request.form.get('reason', '').strip()

        try:
            slot_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Format de date invalide', "danger")
            return redirect(url_for('professional_unavailable_slots'))

        if slot_date < date.today():
            flash('Vous ne pouvez pas bloquer une date dans le passé', "danger")
            return redirect(url_for('professional_unavailable_slots'))

        if not start_time or not end_time:
            flash("Heure de début et de fin obligatoires.", "danger")
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

        flash('Créneau indisponible ajouté avec succès!', "success")
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
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
        return redirect(url_for('index'))

    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('professional_unavailable_slots'))

    db.session.delete(slot)
    db.session.commit()
    flash('Créneau indisponible supprimé!', "success")
    return redirect(url_for('professional_unavailable_slots'))

@app.route('/professional/appointments')
@login_required
def professional_appointments():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
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
    A brancher plus tard sur SMS/WhatsApp/Email.
    kind: 'accepted' | 'refused' | 'reminder' | 'pending'
    """
    app.logger.info("[NOTIFY] user=%s kind=%s ap_id=%s brand=%s",
                    user_id, kind, getattr(ap, 'id', None), BRAND_NAME)
# ===========================================================================

@app.route('/professional/appointment/<int:appointment_id>/<action>', methods=['POST'])
@login_required
def professional_appointment_action(appointment_id, action):
    if current_user.user_type != 'professional':
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('index'))

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé', 'danger')
        return redirect(url_for('index'))

    appointment = Appointment.query.get_or_404(appointment_id)
    if appointment.professional_id != professional.id:
        flash('Accès non autorisé', 'danger')
        return redirect(url_for('professional_appointments'))

    if action == 'accept':
        appointment.status = 'confirme'
        db.session.commit()
        notify_user_account_and_phone(user_id=appointment.patient_id, kind='accepted', ap=appointment)
        flash('Rendez-vous accepté!', "success")
    elif action == 'reject':
        appointment.status = 'annule'
        db.session.commit()
        notify_user_account_and_phone(user_id=appointment.patient_id, kind='refused', ap=appointment)
        flash('Rendez-vous refusé!', "success")

    return redirect(url_for('professional_appointments'))

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

            # avance de 30 min
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
        flash("Ce professionnel n'est pas encore validé par l'administration.", "warning")
        return redirect(url_for('professionals'))

    # BLOQUANT : le patient doit avoir un téléphone renseigné
    if not getattr(current_user, 'phone', None) or not _is_valid_phone(current_user.phone):
        flash("Veuillez renseigner votre numéro de téléphone avant de réserver un rendez-vous.", "warning")
        nxt = url_for('book_appointment', professional_id=professional_id)
        return redirect(url_for('account_phone', next=nxt))

    if request.method == 'POST':
        appointment_date = request.form.get('appointment_date', '')
        appointment_time = request.form.get('appointment_time', '')
        consultation_type = request.form.get('consultation_type', 'cabinet')
        notes = request.form.get('notes', '')

        try:
            appointment_date_obj = datetime.strptime(appointment_date, '%Y-%m-%d').date()
        except ValueError:
            flash("Format de date invalide.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        if appointment_date_obj < date.today():
            flash("Impossible de réserver un rendez-vous dans le passé.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        try:
            appointment_datetime = datetime.strptime(
                f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M"
            )
        except ValueError:
            flash("Format de date/heure invalide.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Vérifier disponibilités
        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id,
            day_of_week=day_of_week,
            is_available=True
        ).all()

        if not any(av.start_time <= appointment_time <= av.end_time for av in availabilities):
            flash("Cette heure n'est pas disponible pour ce professionnel.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Déjà réservé ?
        existing = Appointment.query.filter_by(
            professional_id=professional_id,
            appointment_date=appointment_datetime,
            status='confirme'
        ).first()
        if existing:
            flash("Ce créneau est déjà réservé.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Indisponibilités
        slots = UnavailableSlot.query.filter_by(
            professional_id=professional_id,
            date=appointment_date_obj
        ).all()
        if any(s.start_time <= appointment_time <= s.end_time for s in slots):
            flash("Ce créneau est marqué comme indisponible.", "danger")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Créer RDV (statut EN ATTENTE de validation par le pro)
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

        # Notification compte + (plus tard) SMS/WhatsApp
        notify_user_account_and_phone(user_id=current_user.id, kind='pending', ap=appointment)

        flash("Rendez-vous réservé avec succès! Le professionnel confirmera bientôt.", "success")
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

# ===== [TIGHRI_P1:ACCOUNT_PHONE_UPDATE] =====================================
@app.route('/account/phone', methods=['GET', 'POST'])
@login_required
def account_phone():
    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

    if request.method == 'POST':
        phone = (request.form.get('phone') or '').strip()
        if not phone:
            flash("Le numéro de téléphone est obligatoire.", "danger")
            return redirect(url_for('account_phone', next=next_url))
        if not _is_valid_phone(phone):
            flash("Numéro de téléphone invalide. Merci de vérifier.", "danger")
            return redirect(url_for('account_phone', next=next_url))

        try:
            current_user.phone = phone
            db.session.commit()
            flash("Numéro de téléphone mis à jour.", "success")
            return redirect(next_url)
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la mise à jour du téléphone.", "danger")
            return redirect(url_for('account_phone', next=next_url))

    # GET
    return render_template('account_phone.html', next_url=next_url)
# ============================================================================

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
