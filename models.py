# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Identité
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Téléphone utilisateur (utilisé dans les formulaires / contact)
    phone = db.Column(db.String(30))

    # Rôle applicatif: 'patient' | 'professional'
    user_type = db.Column(db.String(20), default='patient')

    # Admin global
    is_admin = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Les UNIQUE créent déjà des index sur username/email.
        db.Index('ix_users_user_type', 'user_type'),
        db.Index('ix_users_is_admin', 'is_admin'),
        db.Index('ix_users_created_at', 'created_at'),
    )

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User id={self.id} {self.username} type={self.user_type} admin={self.is_admin}>"


class Professional(db.Model):
    __tablename__ = "professionals"

    id = db.Column(db.Integer, primary_key=True)

    # Identité / contenu
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    specialty = db.Column(db.String(120))
    experience_years = db.Column(db.Integer)
    consultation_fee = db.Column(db.Float)  # MAD
    image_url = db.Column(db.Text)

    # Dispo & types de consultation
    availability = db.Column(db.String(50), default='disponible')
    consultation_types = db.Column(db.String(120))  # ex: "cabinet,domicile,en_ligne"

    # Localisation (ville), adresse précise + géoloc
    location = db.Column(db.String(120))
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # Téléphone du pro
    phone = db.Column(db.String(30))

    # Réseaux sociaux (URLs)
    facebook_url = db.Column(db.Text)
    instagram_url = db.Column(db.Text)
    tiktok_url = db.Column(db.Text)
    youtube_url = db.Column(db.Text)
    # L’admin doit approuver l’affichage public
    social_links_approved = db.Column(db.Boolean, default=False)

    # Validation par l’admin: 'valide' | 'en_attente' | 'rejete'
    status = db.Column(db.String(20), default='en_attente')

    # ✅ Durée par défaut 45 min et buffer 15 min (modifiables pro + admin)
    consultation_duration_minutes = db.Column(db.Integer, default=45)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15)

    # ✅ Nouveau : mise en avant & rang d’affichage (contrôle admin)
    is_featured = db.Column(db.Boolean, default=False)
    featured_rank = db.Column(db.Integer)  # 1 = tout en haut, puis 2, 3, ...

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        # Index utiles pour la recherche/front
        db.Index('ix_professionals_name', 'name'),
        db.Index('ix_professionals_specialty', 'specialty'),
        db.Index('ix_professionals_location', 'location'),
        db.Index('ix_professionals_address', 'address'),
        db.Index('ix_professionals_status', 'status'),
        db.Index('ix_professionals_availability', 'availability'),
        db.Index('ix_professionals_created_at', 'created_at'),
        # Index multi-colonnes pour les filtres/search (LIKE sur plusieurs champs)
        db.Index('ix_professionals_search', 'name', 'specialty', 'location', 'address'),
        # ✅ Index pour le classement admin
        db.Index('ix_professionals_is_featured', 'is_featured'),
        db.Index('ix_professionals_featured_rank', 'featured_rank'),
    )

    def __repr__(self):
        return f"<Professional id={self.id} {self.name} [{self.specialty}] status={self.status}>"


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)

    appointment_date = db.Column(db.DateTime, nullable=False)

    # 'cabinet' | 'domicile' | 'en_ligne'
    consultation_type = db.Column(db.String(20), default='cabinet')

    # 'en_attente' | 'confirme' | 'annule'
    status = db.Column(db.String(20), default='en_attente')

    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations (jointes pour éviter le N+1 dans les listes)
    patient = db.relationship('User', backref='appointments', lazy='joined')
    professional = db.relationship('Professional', backref='appointments', lazy='joined')

    __table_args__ = (
        db.Index('ix_appointments_professional_date', 'professional_id', 'appointment_date'),
        db.Index('ix_appointments_patient', 'patient_id'),
        db.Index('ix_appointments_status', 'status'),
        db.Index('ix_appointments_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<Appt id={self.id} pro={self.professional_id} patient={self.patient_id} at={self.appointment_date} status={self.status}>"


# ✅ Déplacés ici depuis app.py pour être accessibles aussi côté admin
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
