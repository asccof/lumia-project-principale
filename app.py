from flask import Flask, render_template
from flask_login import LoginManager
from werkzeug.security import generate_password_hash
from werkzeug.middleware.dispatcher import DispatcherMiddleware
import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- App principale ---
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True  # Render est en HTTPS

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

# --- Config DB (une seule instance SQLAlchemy : celle de models.py) ---
from models import db, User, Professional, Appointment  # <-- réutilise l'instance existante

uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL")
if not uri:
    raise RuntimeError("DATABASE_URL manquant : lie ta base Postgres dans Render.")
uri = _normalize_pg_uri(uri)

app.config["SQLALCHEMY_DATABASE_URI"] = uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}

# Attacher l'instance SQLAlchemy UNE FOIS à l'app principale
db.init_app(app)

# Login manager (unique ici)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# --- Monter le sous-serveur admin (sa propre Flask app) ---
from admin_server import app as admin_app  # importe après config DB
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/admin": admin_app})

# --- Créer les tables + seed un admin si absent ---
with app.app_context():
    db.create_all()
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

# --------------------------------------------------------------------
# ↓ Tes routes “site public” continuent ici ↓
# --------------------------------------------------------------------
@app.get("/")
def home():
    return render_template("index.html")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), default='patient')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

    appointments_as_patient = db.relationship(
        'Appointment', foreign_keys='Appointment.patient_id', backref='patient', lazy=True
    )

class Professional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    consultation_fee = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200))
    specialty = db.Column(db.String(50), nullable=False)
    availability = db.Column(db.String(100), default='disponible')
    consultation_types = db.Column(db.String(100), default='cabinet')
    location = db.Column(db.String(100), default='Casablanca')
    phone = db.Column(db.String(20), default='+212 6 XX XX XX XX')
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointments = db.relationship('Appointment', backref='professional', lazy=True)
    availabilities = db.relationship('ProfessionalAvailability', backref='professional', lazy=True, cascade='all, delete-orphan')
    unavailable_slots = db.relationship('UnavailableSlot', backref='professional', lazy=True, cascade='all, delete-orphan')

class ProfessionalAvailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UnavailableSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='en_attente')
    consultation_type = db.Column(db.String(20), default='cabinet')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ======================
# Routes principales
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
        professionals = base_query.filter(
            or_(
                Professional.name.ilike(f'%{search_query}%'),
                Professional.specialty.ilike(f'%{search_query}%'),
                Professional.location.ilike(f'%{search_query}%'),
                Professional.description.ilike(f'%{search_query}%')
            )
        ).all()
    elif specialty != 'all':
        professionals = base_query.filter_by(specialty=specialty).all()
    else:
        professionals = base_query.all()

    return render_template('professionals.html', professionals=professionals, specialty=specialty, search_query=search_query)

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

        # Créer l'utilisateur (type professional)
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type='professional'
        )
        db.session.add(user)
        db.session.commit()

        # Créer le profil professionnel (lié par le nom comme dans l’original)
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
        # Supprimer les anciennes dispos
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        # Ajouter les nouvelles pour chaque jour 0..6
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

        # Validation de la date
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
        flash('Rendez-vous accepté!')
    elif action == 'reject':
        appointment.status = 'annule'
        flash('Rendez-vous refusé!')

    db.session.commit()
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
        'availability': p.availability
    } for p in pros])


@app.route('/api/professional/<int:professional_id>/available-slots')
def api_available_slots(professional_id):
    """API pour récupérer les créneaux disponibles d'un professionnel."""
    from datetime import timedelta

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

            # indisponibilités
            is_unavailable = any(
                (slot_start >= datetime.strptime(u.start_time, '%H:%M').time()
                 and slot_start < datetime.strptime(u.end_time, '%H:%M').time())
                for u in unavailable_slots
            )

            # déjà réservé
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
# Réservation
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

        # Vérifier les disponibilités
        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id,
            day_of_week=day_of_week,
            is_available=True
        ).all()

        if not any(av.start_time <= appointment_time <= av.end_time for av in availabilities):
            flash("Cette heure n'est pas disponible pour ce professionnel.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Vérifier déjà réservé
        existing = Appointment.query.filter_by(
            professional_id=professional_id,
            appointment_date=appointment_datetime,
            status='confirme'
        ).first()
        if existing:
            flash("Ce créneau est déjà réservé.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Vérifier indisponibilités
        slots = UnavailableSlot.query.filter_by(
            professional_id=professional_id,
            date=appointment_date_obj
        ).all()
        if any(s.start_time <= appointment_time <= s.end_time for s in slots):
            flash("Ce créneau est marqué comme indisponible.")
            return redirect(url_for('book_appointment', professional_id=professional_id))

        # Créer RDV
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

        flash("Rendez-vous réservé avec succès! Le professionnel confirmera bientôt.")
        return redirect(url_for('my_appointments'))

    # Affichage
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id, is_available=True
    ).all()
    from datetime import timedelta
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
        'database_file': 'tighri.db',
        'server_port': 5000,
        'admin_port': 8080
    }
    return render_template('site_status.html', status=status, stats=stats)


# ======================
# Montage Admin & Run
# ======================

mounted_admin = DispatcherMiddleware(app.wsgi_app, {
    '/admin': admin_app.wsgi_app
})
app.wsgi_app = mounted_admin

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@tighri.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional'
            )
            db.session.add(admin)
            db.session.commit()

        if not Professional.query.first():
            examples = [
                Professional(
                    name='Driss Helali',
                    description="Psychologue clinicien, expert en TCC, 10 ans d'expérience à Casablanca.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=400,
                    image_url='https://images.unsplash.com/photo-1559839734-2b71ea197ec2?w=300&h=300&fit=crop',
                    location='Casablanca',
                    experience_years=10
                ),
                Professional(
                    name='Nada Helali',
                    description="Psychologue pour enfants et ados, approche bienveillante.",
                    specialty='Psychologue pour Enfants',
                    consultation_fee=350,
                    image_url='https://images.unsplash.com/photo-1594824475545-9d0c7c4951c5?w=300&h=300&fit=crop',
                    location='Rabat',
                    experience_years=7
                )
            ]
            for prof in examples:
                db.session.add(prof)
            db.session.commit()

        app.config['SITE_STATUS'] = {
            'server_started': True,
            'admin_credentials': 'admin / admin123',
            'database_ready': True,
            'startup_time': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        }

    from werkzeug.serving import run_simple
    run_simple('0.0.0.0', 5000, mounted_admin, use_debugger=True, use_reloader=False)
