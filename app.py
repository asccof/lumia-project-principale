from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# Configuration pour production (Render.com)
if os.environ.get('DATABASE_URL'):
    # Production - PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL').replace('postgres://', 'postgresql://')
else:
    # Développement - SQLite
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lumia.db'

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'votre_cle_secrete_ici')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Modèles de base de données
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), default='patient')  # 'patient' ou 'professional'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)
    
    # Relations
    appointments_as_patient = db.relationship('Appointment', foreign_keys='Appointment.patient_id', backref='patient', lazy=True)

class Professional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    consultation_fee = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200))
    specialty = db.Column(db.String(50), nullable=False)
    availability = db.Column(db.String(100), default='disponible')
    consultation_types = db.Column(db.String(100), default='cabinet')  # domicile,cabinet,video
    location = db.Column(db.String(100), default='Casablanca')
    phone = db.Column(db.String(20), default='+212 6 XX XX XX XX')
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')  # en_attente, valide, rejete
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    appointments = db.relationship('Appointment', backref='professional', lazy=True)
    availabilities = db.relationship('ProfessionalAvailability', backref='professional', lazy=True, cascade='all, delete-orphan')
    unavailable_slots = db.relationship('UnavailableSlot', backref='professional', lazy=True, cascade='all, delete-orphan')

class ProfessionalAvailability(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 1=Tuesday, etc.
    start_time = db.Column(db.String(5), nullable=False)  # Format HH:MM
    end_time = db.Column(db.String(5), nullable=False)  # Format HH:MM
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UnavailableSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)  # Date spécifique
    start_time = db.Column(db.String(5), nullable=False)  # Format HH:MM
    end_time = db.Column(db.String(5), nullable=False)  # Format HH:MM
    reason = db.Column(db.String(200))  # Raison (vacances, congé, etc.)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='en_attente')  # en_attente, confirme, annule
    consultation_type = db.Column(db.String(20), default='cabinet')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes principales
@app.route('/')
def index():
    featured_professionals = Professional.query.limit(6).all()
    return render_template('index.html', professionals=featured_professionals)

@app.route('/professionals')
def professionals():
    specialty = request.args.get('specialty', 'all')
    search_query = request.args.get('q', '')
    
    # Base query - seulement les professionnels validés
    base_query = Professional.query.filter_by(status='valide')
    
    if search_query:
        # Recherche par nom, spécialité, ville ou description
        professionals = base_query.filter(
            db.or_(
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

# Routes d'authentification
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Nom d\'utilisateur déjà pris')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email déjà enregistré')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email, password_hash=generate_password_hash(password), user_type='patient')
        db.session.add(user)
        db.session.commit()
        
        flash('Compte patient créé avec succès!')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/professional_register', methods=['GET', 'POST'])
def professional_register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        specialty = request.form.get('specialty', '')
        city = request.form.get('city', '')
        experience = request.form.get('experience', 0)
        description = request.form.get('description', '')
        
        if User.query.filter_by(username=username).first():
            flash('Nom d\'utilisateur déjà pris')
            return redirect(url_for('professional_register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email déjà enregistré')
            return redirect(url_for('professional_register'))
        
        # Créer l'utilisateur
        user = User(
            username=username, 
            email=email, 
            password_hash=generate_password_hash(password), 
            user_type='professional'
        )
        db.session.add(user)
        db.session.commit()
        
        # Créer le profil professionnel
        consultation_fee = float(request.form.get('consultation_fee', 0))
        professional = Professional(
            name=username,
            description=description,
            specialty=specialty,
            location=city,
            experience_years=experience,
            consultation_fee=consultation_fee,
            status='en_attente'  # En attente de validation admin
        )
        db.session.add(professional)
        db.session.commit()
        
        flash('Compte professionnel créé avec succès! Un administrateur validera votre profil.')
        return redirect(url_for('login'))
    
    return render_template('professional_register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.user_type == 'professional':
                flash('Bienvenue dans votre espace professionnel!')
                return redirect(url_for('professional_dashboard'))
            else:
                flash('Connexion réussie!')
                return redirect(url_for('index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/professional_dashboard')
@login_required
def professional_dashboard():
    if current_user.user_type != 'professional':
        flash('Accès non autorisé')
        return redirect(url_for('index'))
    
    # Récupérer le profil professionnel
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash('Profil professionnel non trouvé')
        return redirect(url_for('index'))
    
    # Récupérer les rendez-vous du professionnel
    appointments = Appointment.query.filter_by(professional_id=professional.id).order_by(Appointment.appointment_date.desc()).all()
    
    return render_template('professional_dashboard.html', professional=professional, appointments=appointments)

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
        # Supprimer les anciennes disponibilités
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()
        
        # Ajouter les nouvelles disponibilités
        for day in range(7):  # 0-6 pour les jours de la semaine
            start_time = request.form.get(f'start_time_{day}')
            end_time = request.form.get(f'end_time_{day}')
            is_available = request.form.get(f'available_{day}') == 'on'
            
            if is_available and start_time and end_time:
                availability = ProfessionalAvailability(
                    professional_id=professional.id,
                    day_of_week=day,
                    start_time=start_time,
                    end_time=end_time,
                    is_available=True
                )
                db.session.add(availability)
        
        db.session.commit()
        flash('Disponibilités mises à jour avec succès!')
        return redirect(url_for('professional_availability'))
    
    # Récupérer les disponibilités actuelles
    availabilities = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    availability_dict = {av.day_of_week: av for av in availabilities}
    
    return render_template('professional_availability.html', professional=professional, availabilities=availability_dict)

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
        date = request.form['date']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        reason = request.form.get('reason', '')
        
        # Vérifier que la date n'est pas dans le passé
        from datetime import datetime, date as date_type
        slot_date = datetime.strptime(date, '%Y-%m-%d').date()
        if slot_date < date_type.today():
            flash('Vous ne pouvez pas bloquer une date dans le passé')
            return redirect(url_for('professional_unavailable_slots'))
        
        # Créer le créneau indisponible
        unavailable_slot = UnavailableSlot(
            professional_id=professional.id,
            date=slot_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason
        )
        db.session.add(unavailable_slot)
        db.session.commit()
        
        flash('Créneau indisponible ajouté avec succès!')
        return redirect(url_for('professional_unavailable_slots'))
    
    # Récupérer les créneaux indisponibles
    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional.id).order_by(UnavailableSlot.date.desc()).all()
    
    return render_template('professional_unavailable_slots.html', professional=professional, unavailable_slots=unavailable_slots)

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
    
    # Vérifier que le créneau appartient à ce professionnel
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
    
    appointments = Appointment.query.filter_by(professional_id=professional.id).order_by(Appointment.appointment_date.desc()).all()
    return render_template('professional_appointments.html', professional=professional, appointments=appointments)

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
    
    # Vérifier que le rendez-vous appartient à ce professionnel
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

# Note: L'administration a été déplacée vers un serveur séparé sur le port 8080
# Accédez à l'administration via: http://localhost:8080

# API Routes
@app.route('/api/professionals')
def api_professionals():
    professionals = Professional.query.all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'consultation_fee': p.consultation_fee,
        'image_url': p.image_url,
        'specialty': p.specialty,
        'availability': p.availability
    } for p in professionals])

@app.route('/api/professional/<int:professional_id>/available-slots')
def api_available_slots(professional_id):
    """API pour récupérer les créneaux disponibles d'un professionnel"""
    from datetime import datetime, date, timedelta
    
    professional = Professional.query.get_or_404(professional_id)
    
    # Vérifier que le professionnel est validé
    if professional.status != 'valide':
        return jsonify({'error': 'Professionnel non validé'}), 400
    
    # Récupérer la date demandée (par défaut aujourd'hui)
    requested_date = request.args.get('date', date.today().isoformat())
    try:
        target_date = datetime.strptime(requested_date, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Format de date invalide'}), 400
    
    # Récupérer les disponibilités hebdomadaires
    day_of_week = target_date.weekday()
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id,
        day_of_week=day_of_week,
        is_available=True
    ).all()
    
    # Récupérer les créneaux indisponibles pour cette date
    unavailable_slots = UnavailableSlot.query.filter_by(
        professional_id=professional_id,
        date=target_date
    ).all()
    
    # Récupérer les rendez-vous confirmés pour cette date
    confirmed_appointments = Appointment.query.filter_by(
        professional_id=professional_id,
        status='confirme'
    ).filter(
        db.func.date(Appointment.appointment_date) == target_date
    ).all()
    
    # Générer les créneaux disponibles
    available_slots = []
    
    for availability in availabilities:
        start_time = datetime.strptime(availability.start_time, '%H:%M').time()
        end_time = datetime.strptime(availability.end_time, '%H:%M').time()
        
        # Générer des créneaux de 30 minutes
        current_time = start_time
        while current_time < end_time:
            slot_start = current_time
            slot_end = (datetime.combine(date.today(), current_time) + timedelta(minutes=30)).time()
            
            # Vérifier si ce créneau n'est pas indisponible
            is_unavailable = False
            for unavailable in unavailable_slots:
                unavailable_start = datetime.strptime(unavailable.start_time, '%H:%M').time()
                unavailable_end = datetime.strptime(unavailable.end_time, '%H:%M').time()
                
                if (slot_start >= unavailable_start and slot_start < unavailable_end) or \
                   (slot_end > unavailable_start and slot_end <= unavailable_end):
                    is_unavailable = True
                    break
            
            # Vérifier si ce créneau n'est pas déjà réservé
            is_booked = False
            for appointment in confirmed_appointments:
                appointment_time = appointment.appointment_date.time()
                if slot_start <= appointment_time < slot_end:
                    is_booked = True
                    break
            
            if not is_unavailable and not is_booked:
                available_slots.append({
                    'start_time': slot_start.strftime('%H:%M'),
                    'end_time': slot_end.strftime('%H:%M'),
                    'available': True
                })
            
            current_time = slot_end
    
    return jsonify({
        'professional_id': professional_id,
        'date': target_date.isoformat(),
        'available_slots': available_slots
    })

@app.route('/book_appointment/<int:professional_id>', methods=['GET', 'POST'])
@login_required
def book_appointment(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    
    # Vérifier que le professionnel est validé
    if professional.status != 'valide':
        flash('Ce professionnel n\'est pas encore validé par l\'administration.')
        return redirect(url_for('professionals'))
    
    if request.method == 'POST':
        appointment_date = request.form['appointment_date']
        appointment_time = request.form['appointment_time']
        consultation_type = request.form['consultation_type']
        notes = request.form.get('notes', '')
        
        # Combiner date et heure
        from datetime import datetime
        datetime_str = f"{appointment_date} {appointment_time}"
        appointment_datetime = datetime.strptime(datetime_str, '%Y-%m-%d %H:%M')
        
        # Vérifier les disponibilités du professionnel
        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id,
            day_of_week=day_of_week,
            is_available=True
        ).all()
        
        # Vérifier si l'heure est dans les disponibilités
        time_str = appointment_time
        is_available = False
        for availability in availabilities:
            if availability.start_time <= time_str <= availability.end_time:
                is_available = True
                break
        
        if not is_available:
            flash('Cette heure n\'est pas disponible pour ce professionnel.')
            return redirect(url_for('book_appointment', professional_id=professional_id))
        
        # Vérifier s'il n'y a pas déjà un rendez-vous à cette heure
        existing_appointment = Appointment.query.filter_by(
            professional_id=professional_id,
            appointment_date=appointment_datetime,
            status='confirme'
        ).first()
        
        if existing_appointment:
            flash('Ce créneau est déjà réservé.')
            return redirect(url_for('book_appointment', professional_id=professional_id))
        
        # Créer le rendez-vous
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
        
        flash('Rendez-vous réservé avec succès! Le professionnel vous confirmera bientôt.')
        return redirect(url_for('my_appointments'))
    
    # Récupérer les disponibilités pour affichage
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id,
        is_available=True
    ).all()
    
    return render_template('book_appointment.html', professional=professional, availabilities=availabilities)

@app.route('/my_appointments')
@login_required
def my_appointments():
    if current_user.user_type == 'professional':
        # Pour les professionnels, afficher leurs rendez-vous
        appointments = Appointment.query.filter_by(professional_id=current_user.id).all()
    else:
        # Pour les patients, afficher leurs rendez-vous
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
    
    return render_template('my_appointments.html', appointments=appointments)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Créer un admin par défaut si aucun utilisateur n'existe
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@lumia.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional'
            )
            db.session.add(admin)
            db.session.commit()
        
        # Ajouter des professionnels d'exemple si la table est vide
        if not Professional.query.first():
            examples = [
                Professional(
                    name='Driss Helali',
                    description="Psychologue clinicien, expert en thérapie cognitive et comportementale. 10 ans d'expérience à Casablanca. Consultations en français et arabe.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=400,
                    image_url='https://images.unsplash.com/photo-1559839734-2b71ea197ec2?w=300&h=300&fit=crop&crop=face',
                    location='Casablanca',
                    experience_years=10
                ),
                Professional(
                    name='Nada Helali',
                    description="Psychologue pour enfants et adolescents. Approche bienveillante et adaptée aux jeunes. Consultations à domicile et en ligne.",
                    specialty='Psychologue pour Enfants',
                    consultation_fee=350,
                    image_url='https://images.unsplash.com/photo-1594824475545-9d0c7c4951c5?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=7
                ),
                Professional(
                    name='Hatim Heleli',
                    description="Thérapeute familial et conjugal. Spécialisé dans la résolution de conflits et la communication. Consultations en vidéo et cabinet.",
                    specialty='Thérapeute Familial',
                    consultation_fee=450,
                    image_url='https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?w=300&h=300&fit=crop&crop=face',
                    location='Marrakech',
                    experience_years=12
                ),
                Professional(
                    name='Hajar Heleli',
                    description="Psychologue spécialisée en EMDR et thérapie des traumatismes. Cabinet à Rabat et consultations en ligne.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=500,
                    image_url='https://images.unsplash.com/photo-1582750433449-648ed127bb54?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=9
                ),
                Professional(
                    name='Loubna Moubine',
                    description="Coach en développement personnel et gestion du stress. Accompagnement en ligne et en présentiel.",
                    specialty='Coach en Développement Personnel',
                    consultation_fee=300,
                    image_url='https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=300&h=300&fit=crop&crop=face',
                    location='Casablanca',
                    experience_years=6
                ),
                Professional(
                    name='Yassine El Amrani',
                    description="Thérapeute de couple et sexologue. Consultations en cabinet à Marrakech et en ligne.",
                    specialty='Thérapeute de Couple',
                    consultation_fee=450,
                    image_url='https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=300&h=300&fit=crop&crop=face',
                    location='Marrakech',
                    experience_years=11
                ),
                Professional(
                    name='Imane Berrada',
                    description="Psychologue clinicienne, spécialisée en gestion des émotions et anxiété. Consultations à Rabat.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=400,
                    image_url='https://images.unsplash.com/photo-1511367461989-f85a21fda167?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=8
                ),
                Professional(
                    name='Omar El Fassi',
                    description="Coach professionnel, accompagnement en reconversion et orientation. Disponible en ligne.",
                    specialty='Coach en Développement Personnel',
                    consultation_fee=350,
                    image_url='https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=300&h=300&fit=crop&crop=face',
                    location='Fès',
                    experience_years=5
                )
            ]
            for prof in examples:
                db.session.add(prof)
            db.session.commit()

    print("🚀 Serveur principal Tighri démarré sur http://localhost:5000")
    print("📧 Connexion admin: admin / admin123")
    app.run(debug=True, port=5000) 