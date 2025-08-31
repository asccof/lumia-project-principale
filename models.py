# models.py — une seule instance SQLAlchemy, aucun Flask() ici
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()  # <— unique instance partagée

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    user_type = db.Column(db.String(20), default='patient')  # 'patient' ou 'professional'
    is_admin = db.Column(db.Boolean, default=False)
    phone = db.Column(db.String(50))  # requis côté formulaire

    # RDV pris par l'utilisateur (patient)
    appointments = db.relationship(
        'Appointment',
        backref='patient',
        lazy='dynamic',
        foreign_keys='Appointment.patient_id'
    )

class Professional(db.Model):
    __tablename__ = 'professionals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    consultation_fee = db.Column(db.Float, default=0.0)
    image_url = db.Column(db.String(255))
    specialty = db.Column(db.String(120))
    availability = db.Column(db.String(50), default='disponible')
    consultation_types = db.Column(db.String(120))  # ex: "cabinet,domicile,en_ligne"
    location = db.Column(db.String(120))            # ville (fallback)
    phone = db.Column(db.String(50))
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')  # 'valide', 'en_attente', 'rejete'

    # Adresse exacte + géolocalisation
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # Liens réseaux sociaux + validation admin
    facebook_url = db.Column(db.String(255))
    instagram_url = db.Column(db.String(255))
    tiktok_url = db.Column(db.String(255))
    youtube_url = db.Column(db.String(255))
    social_links_approved = db.Column(db.Boolean, default=False)

    # RDV avec ce pro
    appointments = db.relationship(
        'Appointment',
        backref='professional',
        lazy='dynamic',
        foreign_keys='Appointment.professional_id'
    )

    # Avis
    reviews = db.relationship(
        'ProfessionalReview',
        backref='professional',
        lazy='dynamic',
        foreign_keys='ProfessionalReview.professional_id',
        cascade="all, delete-orphan"
    )

class Appointment(db.Model):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    consultation_type = db.Column(db.String(20))  # 'cabinet' | 'domicile' | 'video' | 'en_ligne'
    status = db.Column(db.String(20), default='en_attente')  # 'confirme', 'en_attente', 'annule'
    notes = db.Column(db.Text)

class ProfessionalReview(db.Model):
    __tablename__ = 'professional_reviews'
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship('User', lazy='joined')
