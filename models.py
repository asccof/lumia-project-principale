# models.py
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# --- Users ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    user_type = db.Column(db.String(32), default='patient')  # patient | professional
    phone = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Flask-Login
    def get_id(self):  # pragma: no cover
        return str(self.id)

# --- Professionals ---
class Professional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    specialty = db.Column(db.String(255))
    status = db.Column(db.String(32), default='en_attente')  # en_attente | valide | rejete

    # coordonnées
    location = db.Column(db.String(255))   # ville
    address = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    latitude = db.Column(db.String(64))
    longitude = db.Column(db.String(64))

    # présentation / média
    image_url = db.Column(db.String(1024))
    description = db.Column(db.Text)

    # pricing / planning
    consultation_fee = db.Column(db.Float)
    consultation_duration_minutes = db.Column(db.Integer, default=45)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15)
    availability = db.Column(db.String(32), default='disponible')  # disponible | indisponible
    experience_years = db.Column(db.Integer)
    consultation_types = db.Column(db.String(255))  # "cabinet,en_ligne,domicile"

    # social
    facebook_url = db.Column(db.String(512))
    instagram_url = db.Column(db.String(512))
    tiktok_url = db.Column(db.String(512))
    youtube_url = db.Column(db.String(512))
    social_links_approved = db.Column(db.Boolean, default=False)

# --- Appointments ---
class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'))
    appointment_date = db.Column(db.DateTime)
    consultation_type = db.Column(db.String(32))  # cabinet | domicile | en_ligne
    status = db.Column(db.String(32), default='en_attente')  # en_attente | confirme | annule

    patient = db.relationship('User', backref='appointments', lazy='joined')
    professional = db.relationship('Professional', backref='appointments', lazy='joined')

# --- Classement manuel des pros ---
class ProfessionalOrder(db.Model):
    __tablename__ = 'professional_order'
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), primary_key=True)
    order_priority = db.Column(db.Integer, nullable=False, default=9999)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    professional = db.relationship('Professional', backref='order_entry')

# --- Disponibilités récurrentes (facultatif; minimal pour tes écrans) ---
class ProfessionalAvailabilityWindow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    weekday = db.Column(db.Integer, nullable=False)  # 0=lundi … 6=dimanche
    start_time = db.Column(db.String(5))  # "08:00"
    end_time = db.Column(db.String(5))    # "12:00"

    professional = db.relationship('Professional', backref='availability_windows')

# --- Indisponibilités ponctuelles ---
class ProfessionalUnavailableSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(255))

    professional = db.relationship('Professional', backref='unavailable_slots')

# --- Modération avis & liens sociaux (ultra simple pour tes pages) ---
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rating = db.Column(db.Integer, default=0)
    comment = db.Column(db.Text)
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship('Professional', lazy='joined')
    user = db.relationship('User', lazy='joined')

class SocialLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'))
    platform = db.Column(db.String(32))
    url = db.Column(db.String(1024))
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship('Professional', lazy='joined')
