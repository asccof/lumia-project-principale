# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

# ======================
# Utilisateurs
# ======================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    # Identité
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # nullable=True pour autoriser les comptes créés via Google (sans mot de passe local)
    password_hash = db.Column(db.String(255), nullable=True)

    # Téléphone utilisateur
    phone = db.Column(db.String(30))

    # Rôle applicatif: 'patient' | 'professional'
    user_type = db.Column(db.String(20), default='patient')

    # Admin global
    is_admin = db.Column(db.Boolean, default=False)

    # --- Liaison OAuth (Google, etc.) ---
    oauth_provider = db.Column(db.String(30))                 # ex: 'google'
    oauth_sub = db.Column(db.String(255), unique=True, index=True)  # identifiant 'sub' Google
    picture_url = db.Column(db.Text)                          # photo de profil Google
    full_name = db.Column(db.String(120))                     # nom affiché Google

    # Reset password
    reset_token_hash = db.Column(db.String(255))
    reset_token_expires_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_users_user_type', 'user_type'),
        db.Index('ix_users_is_admin', 'is_admin'),
        db.Index('ix_users_created_at', 'created_at'),
    )

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User id={self.id} {self.username} type={self.user_type} admin={self.is_admin}>"

# ======================
# Référentiels (Phase 1)
# ======================

class City(db.Model):
    __tablename__ = "cities"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Specialty(db.Model):
    __tablename__ = "specialties"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    category = db.Column(db.String(80))  # ex: Psychothérapie/Coaching…

# Pivot Pro <-> Spécialités secondaires
professional_specialties = db.Table(
    "professional_specialties",
    db.Column("professional_id", db.Integer, db.ForeignKey("professionals.id"), primary_key=True),
    db.Column("specialty_id", db.Integer, db.ForeignKey("specialties.id"), primary_key=True),
)

# ======================
# Professionnels
# ======================
class Professional(db.Model):
    __tablename__ = "professionals"

    id = db.Column(db.Integer, primary_key=True)

    # Identité / contenu
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)

    # Ancienne spécialité texte (compat ascendante)
    specialty = db.Column(db.String(120))

    # Normalisation (Phase 1)
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id"))
    city = db.relationship("City", lazy="joined")

    primary_specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id"))
    primary_specialty = db.relationship("Specialty", foreign_keys=[primary_specialty_id], lazy="joined")

    specialties = db.relationship("Specialty", secondary=professional_specialties, lazy="subquery")

    # Expérience / tarif
    experience_years = db.Column(db.Integer)
    consultation_fee = db.Column(db.Float)  # MAD
    image_url = db.Column(db.Text)

    # Dispo & types de consultation
    availability = db.Column(db.String(50), default='disponible')
    # ex: "cabinet,domicile,en_ligne"
    consultation_types = db.Column(db.String(120))

    # Localisation (ancienne colonne texte), adresse précise + géoloc
    location = db.Column(db.String(120))
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # Téléphone du pro
    phone = db.Column(db.String(30))

    # Réseaux sociaux (URLs) + approbation admin
    facebook_url = db.Column(db.Text)
    instagram_url = db.Column(db.Text)
    tiktok_url = db.Column(db.Text)
    youtube_url = db.Column(db.Text)
    social_links_approved = db.Column(db.Boolean, default=False)

    # Validation par l’admin: 'valide' | 'en_attente' | 'rejete'
    status = db.Column(db.String(20), default='en_attente')

    # Durée par défaut 45 min et buffer 15 min
    consultation_duration_minutes = db.Column(db.Integer, default=45)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15)

    # Mise en avant locale
    is_featured = db.Column(db.Boolean, default=False)
    featured_rank = db.Column(db.Integer)  # 1 = top

    # ✅ Badges (Phase 1)
    certified_tighri = db.Column(db.Boolean, default=False)
    approved_anthecc = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ✅ AJOUT: relation non intrusive vers la galerie
    photos = db.relationship(
        "ProfessionalPhoto",
        backref="professional",
        lazy="select",
        cascade="all, delete-orphan",
        order_by="desc(ProfessionalPhoto.created_at)",
    )

    __table_args__ = (
        db.Index('ix_professionals_name', 'name'),
        db.Index('ix_professionals_specialty', 'specialty'),
        db.Index('ix_professionals_location', 'location'),
        db.Index('ix_professionals_address', 'address'),
        db.Index('ix_professionals_status', 'status'),
        db.Index('ix_professionals_availability', 'availability'),
        db.Index('ix_professionals_created_at', 'created_at'),
        db.Index('ix_professionals_search', 'name', 'specialty', 'location', 'address'),
        db.Index('ix_professionals_is_featured', 'is_featured'),
        db.Index('ix_professionals_featured_rank', 'featured_rank'),
    )

    def __repr__(self):
        return f"<Professional id={self.id} {self.name} [{self.specialty}] status={self.status}>"

# ======================
# Rendez-vous & disponibilité
# ======================
class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    # Historique conservé : nullable + SET NULL côté DB
    patient_id = db.Column(
        db.Integer,
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True
    )
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)

    appointment_date = db.Column(db.DateTime, nullable=False)

    # 'cabinet' | 'domicile' | 'en_ligne'
    consultation_type = db.Column(db.String(20), default='cabinet')

    # 'en_attente' | 'confirme' | 'annule'
    status = db.Column(db.String(20), default='en_attente')

    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # passive_deletes sur le backref pour laisser la DB gérer le SET NULL
    patient = db.relationship(
        'User',
        backref=db.backref('appointments', passive_deletes=True),
        lazy='joined',
        passive_deletes=True,
    )
    professional = db.relationship('Professional', backref='appointments', lazy='joined')

    __table_args__ = (
        db.Index('ix_appointments_professional_date', 'professional_id', 'appointment_date'),
        db.Index('ix_appointments_patient', 'patient_id'),
        db.Index('ix_appointments_status', 'status'),
        db.Index('ix_appointments_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<Appt id={self.id} pro={self.professional_id} patient={self.patient_id} at={self.appointment_date} status={self.status}>"

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
# ✅ AJOUT : Galerie de photos (max 3 par pro)
# ======================
class ProfessionalPhoto(db.Model):
    __tablename__ = "professional_photos"

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = db.Column(db.Text, nullable=False)  # ex: "uuid.jpg" (stocké sous /media/profiles/)
    is_primary = db.Column(db.Boolean, default=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_professional_photos_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<ProfessionalPhoto id={self.id} pro={self.professional_id} primary={self.is_primary} file={self.filename}>"
