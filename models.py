# models.py — version propre (contrat-fix)
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()

# ======================
# Utilisateurs
# ======================
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(30))
    user_type = db.Column(db.String(20), default='patient')
    is_admin = db.Column(db.Boolean, default=False)

    # OAuth
    oauth_provider = db.Column(db.String(30))
    oauth_sub = db.Column(db.String(255), unique=True, index=True)
    picture_url = db.Column(db.Text)
    full_name = db.Column(db.String(120))

    # Reset password
    reset_token_hash = db.Column(db.String(255))
    reset_token_expires_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_users_user_type', 'user_type'),
        db.Index('ix_users_is_admin', 'is_admin'),
        db.Index('ix_users_created_at', 'created_at'),
    )

    def get_id(self): return str(self.id)
    def __repr__(self): return f"<User id={self.id} {self.username} type={self.user_type} admin={self.is_admin}>"


# ======================
# Référentiels
# ======================
class City(db.Model):
    __tablename__ = "cities"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

    __table_args__ = (
        db.Index("ix_cities_name", "name"),
    )

    def __repr__(self): return f"<City id={self.id} {self.name}>"


class Specialty(db.Model):
    __tablename__ = "specialties"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    # category = famille (Psychothérapie, Coaching, …)
    category = db.Column(db.String(120))

    __table_args__ = (
        db.Index("ix_specialties_name", "name"),
        db.Index("ix_specialties_category", "category"),
    )

    def __repr__(self): return f"<Specialty id={self.id} {self.name} cat={self.category or '-'}>"


# Pivot Pro <-> Spécialités secondaires
professional_specialties = db.Table(
    "professional_specialties",
    db.Column(
        "professional_id",
        db.Integer,
        db.ForeignKey("professionals.id", ondelete="CASCADE"),
        primary_key=True
    ),
    db.Column(
        "specialty_id",
        db.Integer,
        db.ForeignKey("specialties.id", ondelete="CASCADE"),
        primary_key=True
    ),
    db.Index("ix_prof_spec_professional", "professional_id"),
    db.Index("ix_prof_spec_specialty", "specialty_id"),
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
    city_id = db.Column(db.Integer, db.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True)
    city = db.relationship("City", lazy="joined", backref=db.backref("professionals", lazy="dynamic"))

    primary_specialty_id = db.Column(db.Integer, db.ForeignKey("specialties.id", ondelete="SET NULL"), nullable=True)
    primary_specialty = db.relationship(
        "Specialty",
        foreign_keys=[primary_specialty_id],
        lazy="joined",
        backref=db.backref("primary_for", lazy="dynamic")
    )

    specialties = db.relationship(
        "Specialty",
        secondary=professional_specialties,
        lazy="subquery",
        backref=db.backref("professionals", lazy="dynamic")
    )

    # Expérience / tarif
    experience_years = db.Column(db.Integer)
    consultation_fee = db.Column(db.Float)  # MAD

    # Images
    image_url = db.Column(db.Text)
    image_url2 = db.Column(db.Text)
    image_url3 = db.Column(db.Text)

    # Dispo & types de consultation
    availability = db.Column(db.String(50), default='disponible')
    # ex: "cabinet,domicile,en_ligne"
    consultation_types = db.Column(db.String(120))

    # Localisation et contact
    location = db.Column(db.String(120))
    address = db.Column(db.String(255))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    phone = db.Column(db.String(30))

    # Réseaux sociaux + approbation admin
    facebook_url = db.Column(db.Text)
    instagram_url = db.Column(db.Text)
    tiktok_url = db.Column(db.Text)
    youtube_url = db.Column(db.Text)
    social_links_approved = db.Column(db.Boolean, default=False)

    # Validation / mise en avant
    status = db.Column(db.String(20), default='en_attente')
    is_featured = db.Column(db.Boolean, default=False)
    featured_rank = db.Column(db.Integer)
    certified_tighri = db.Column(db.Boolean, default=False)
    approved_anthecc = db.Column(db.Boolean, default=False)

    # Paramètres RDV
    consultation_duration_minutes = db.Column(db.Integer, default=45)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

    @property
    def consultation_types_list(self):
        raw = (self.consultation_types or "").strip()
        return [t for t in (raw.split(",") if raw else []) if t]


# ======================
# Dossier patient (profil)
# ======================
class PatientProfile(db.Model):
    __tablename__ = "patient_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    # Champs vus dans les logs / nécessaires
    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    birth_date = db.Column(db.Date)
    language = db.Column(db.String(10))             # 'fr', 'ar', 'en'
    preferred_contact = db.Column(db.String(30))     # 'email', 'phone', 'sms', 'whatsapp'
    notes_public = db.Column(db.Text)
    emergency_contact = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship(
        "User",
        backref=db.backref("patient_profile", uselist=False, passive_deletes=True),
        lazy="joined"
    )

    __table_args__ = (
        db.Index("ix_patient_profiles_user", "user_id"),
        db.Index("ix_patient_profiles_last_first", "last_name", "first_name"),
        db.Index("ix_patient_profiles_created", "created_at"),
    )

    def __repr__(self):
        return f"<PatientProfile id={self.id} user={self.user_id} {self.last_name or ''} {self.first_name or ''}>"


# ======================
# Messagerie: fils de discussion
# ======================
class MessageThread(db.Model):
    __tablename__ = "message_threads"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    is_anonymous = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_threads_patient", "patient_id"),
        db.Index("ix_threads_pro", "professional_id"),
        db.UniqueConstraint("patient_id", "professional_id", name="uq_thread_patient_pro"),
    )

    def __repr__(self):
        return f"<MessageThread id={self.id} p={self.patient_id} pro={self.professional_id}>"


# ======================
# Séances (thérapie / coaching)
# ======================
class TherapySession(db.Model):
    __tablename__ = "therapy_sessions"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL"))

    started_at = db.Column(db.DateTime, nullable=False)     # début de séance
    ended_at = db.Column(db.DateTime)                        # fin (optionnel)
    duration_minutes = db.Column(db.Integer)                 # pratique pour les listings
    notes_private = db.Column(db.Text)                       # notes privées pro

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_ts_patient", "patient_id"),
        db.Index("ix_ts_professional", "professional_id"),
        db.Index("ix_ts_started", "started_at"),
    )

    def __repr__(self):
        return f"<TherapySession id={self.id} p={self.patient_id} pro={self.professional_id} at={self.started_at}>"


# ======================
# Antécédents médicaux / historiques
# ======================
class MedicalHistory(db.Model):
    __tablename__ = "medical_histories"

    id = db.Column(db.Integer, primary_key=True)

    # Liens
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='SET NULL'))

    # Contenu
    title = db.Column(db.String(200))     # court résumé (optionnel)
    details = db.Column(db.Text)          # texte libre (antécédents, traitements, etc.)

    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    patient = db.relationship('User', lazy='joined', foreign_keys=[patient_id])
    professional = db.relationship('Professional', lazy='joined', foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_mh_patient", "patient_id"),
        db.Index("ix_mh_professional", "professional_id"),
        db.Index("ix_mh_created", "created_at"),
    )

    def __repr__(self):
        return f"<MedicalHistory id={self.id} patient={self.patient_id} pro={self.professional_id}>"


# ======================
# Rendez-vous & disponibilité
# ======================
class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)

    appointment_date = db.Column(db.DateTime, nullable=False)
    consultation_type = db.Column(db.String(20), default='cabinet')  # 'cabinet' | 'domicile' | 'en_ligne'
    status = db.Column(db.String(20), default='en_attente')           # 'en_attente' | 'confirme' | 'annule'
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship(
        'User',
        backref=db.backref('appointments', passive_deletes=True),
        lazy='joined',
        passive_deletes=True
    )
    professional = db.relationship('Professional', backref=db.backref('appointments', passive_deletes=True), lazy='joined')

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
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0..6
    start_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)    # "HH:MM"
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship('Professional', backref=db.backref('availabilities', passive_deletes=True))


class UnavailableSlot(db.Model):
    __tablename__ = "unavailable_slots"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship('Professional', backref=db.backref('unavailable_slots', passive_deletes=True))
