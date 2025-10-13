# models.py — version alignée (contrat-fix)
from extensions import db
from flask_login import UserMixin
from datetime import datetime, date  # 'date' peut rester utile


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
    user_type = db.Column(db.String(20), default="patient")
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
        db.Index("ix_users_user_type", "user_type"),
        db.Index("ix_users_is_admin", "is_admin"),
        db.Index("ix_users_created_at", "created_at"),
    )

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<User id={self.id} {self.username} type={self.user_type} admin={self.is_admin}>"


# ======================
# Référentiels
# ======================
class City(db.Model):
    __tablename__ = "cities"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

    __table_args__ = (db.Index("ix_cities_name", "name"),)

    def __repr__(self):
        return f"<City id={self.id} {self.name}>"


class Specialty(db.Model):
    __tablename__ = "specialties"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    category = db.Column(db.String(120))  # famille (Psychothérapie, Coaching, …)

    __table_args__ = (
        db.Index("ix_specialties_name", "name"),
        db.Index("ix_specialties_category", "category"),
    )

    def __repr__(self):
        return f"<Specialty id={self.id} {self.name} cat={self.category or '-'}>"


# Pivot Pro <-> Spécialités secondaires
professional_specialties = db.Table(
    "professional_specialties",
    db.Column(
        "professional_id",
        db.Integer,
        db.ForeignKey("professionals.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column(
        "specialty_id",
        db.Integer,
        db.ForeignKey("specialties.id", ondelete="CASCADE"),
        primary_key=True,
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
    city_id = db.Column(
        db.Integer, db.ForeignKey("cities.id", ondelete="SET NULL"), nullable=True
    )
    city = db.relationship(
        "City", lazy="joined", backref=db.backref("professionals", lazy="dynamic")
    )

    primary_specialty_id = db.Column(
        db.Integer, db.ForeignKey("specialties.id", ondelete="SET NULL"), nullable=True
    )
    primary_specialty = db.relationship(
        "Specialty",
        foreign_keys=[primary_specialty_id],
        lazy="joined",
        backref=db.backref("primary_for", lazy="dynamic"),
    )

    specialties = db.relationship(
        "Specialty",
        secondary=professional_specialties,
        lazy="subquery",
        backref=db.backref("professionals", lazy="dynamic"),
    )

    # Expérience / tarif
    experience_years = db.Column(db.Integer)
    consultation_fee = db.Column(db.Float)  # MAD

    # Images
    image_url = db.Column(db.Text)
    image_url2 = db.Column(db.Text)
    image_url3 = db.Column(db.Text)

    # Dispo & types de consultation
    availability = db.Column(db.String(50), default="disponible")
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
    status = db.Column(db.String(20), default="en_attente")
    is_featured = db.Column(db.Boolean, default=False)
    featured_rank = db.Column(db.Integer)
    certified_tighri = db.Column(db.Boolean, default=False)
    approved_anthecc = db.Column(db.Boolean, default=False)

    # Paramètres RDV
    consultation_duration_minutes = db.Column(db.Integer, default=45)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_professionals_name", "name"),
        db.Index("ix_professionals_specialty", "specialty"),
        db.Index("ix_professionals_location", "location"),
        db.Index("ix_professionals_address", "address"),
        db.Index("ix_professionals_status", "status"),
        db.Index("ix_professionals_availability", "availability"),
        db.Index("ix_professionals_created_at", "created_at"),
        db.Index("ix_professionals_search", "name", "specialty", "location", "address"),
        db.Index("ix_professionals_is_featured", "is_featured"),
        db.Index("ix_professionals_featured_rank", "featured_rank"),
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
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    birth_date = db.Column(db.Date)
    language = db.Column(db.String(10))  # 'fr', 'ar', 'en'
    preferred_contact = db.Column(db.String(30))  # 'email', 'phone', 'sms', 'whatsapp'
    notes_public = db.Column(db.Text)
    emergency_contact = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship(
        "User",
        backref=db.backref("patient_profile", uselist=False, passive_deletes=True),
        lazy="joined",
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
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )

    is_anonymous = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship(
        "Professional", lazy="joined", foreign_keys=[professional_id]
    )

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
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    # Champs réels en base (alignés)
    start_at = db.Column(db.DateTime, nullable=True)
    end_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="planifie")  # planifie | termine | annule
    mode = db.Column(db.String(20), default="cabinet")  # cabinet | domicile | en_ligne
    meet_url = db.Column(db.Text)
    appointment_id = db.Column(
        db.Integer, db.ForeignKey("appointments.id", ondelete="SET NULL")
    )

    # Champs texte/extra
    duration_minutes = db.Column(db.Integer)
    notes_private = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship(
        "Professional", lazy="joined", foreign_keys=[professional_id]
    )
    appointment = db.relationship(
        "Appointment", lazy="joined", foreign_keys=[appointment_id]
    )

    __table_args__ = (
        db.Index("ix_ts_patient", "patient_id"),
        db.Index("ix_ts_professional", "professional_id"),
        db.Index("ix_ts_start", "start_at"),
        db.Index("ix_ts_status", "status"),
    )

    # ---- Compatibilité ascendante (les anciennes routes lisaient started_at/ended_at)
    @property
    def started_at(self):
        return self.start_at

    @property
    def ended_at(self):
        return self.end_at

    def __repr__(self):
        return f"<TherapySession id={self.id} p={self.patient_id} pro={self.professional_id} start={self.start_at}>"


# ======================
# Antécédents médicaux / historiques
# ======================
class MedicalHistory(db.Model):
    __tablename__ = "medical_histories"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    # Champs legacy
    title = db.Column(db.String(200))
    details = db.Column(db.Text)

    # Champs réellement utilisés
    summary = db.Column(db.Text)
    custom_fields = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship(
        "Professional", lazy="joined", foreign_keys=[professional_id]
    )

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

    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )

    appointment_date = db.Column(db.DateTime, nullable=False)
    consultation_type = db.Column(db.String(20), default="cabinet")  # 'cabinet' | 'domicile' | 'en_ligne'
    status = db.Column(db.String(20), default="en_attente")  # 'en_attente' | 'confirme' | 'annule'
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship(
        "User",
        backref=db.backref("appointments", passive_deletes=True),
        lazy="joined",
        passive_deletes=True,
    )
    professional = db.relationship(
        "Professional",
        backref=db.backref("appointments", passive_deletes=True),
        lazy="joined",
    )

    __table_args__ = (
        db.Index("ix_appointments_professional_date", "professional_id", "appointment_date"),
        db.Index("ix_appointments_patient", "patient_id"),
        db.Index("ix_appointments_status", "status"),
        db.Index("ix_appointments_created_at", "created_at"),
    )

    def __repr__(self):
        return f"<Appt id={self.id} pro={self.professional_id} patient={self.patient_id} at={self.appointment_date} status={self.status}>"


class ProfessionalAvailability(db.Model):
    __tablename__ = "professional_availabilities"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week = db.Column(db.Integer, nullable=False)  # 0..6
    start_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship(
        "Professional", backref=db.backref("availabilities", passive_deletes=True)
    )


class UnavailableSlot(db.Model):
    __tablename__ = "unavailable_slots"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship(
        "Professional", backref=db.backref("unavailable_slots", passive_deletes=True)
    )


# ======================
# Notes de séance (rattachées à TherapySession)
# ======================
class SessionNote(db.Model):
    __tablename__ = "session_notes"

    id = db.Column(db.Integer, primary_key=True)

    # Liens
    session_id = db.Column(
        db.Integer, db.ForeignKey("therapy_sessions.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    # Contenu
    title = db.Column(db.String(200))  # optionnel
    content = db.Column(db.Text)  # texte de la note

    # Métadonnées
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relations utiles
    session = db.relationship("TherapySession", lazy="joined", foreign_keys=[session_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])
    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])

    __table_args__ = (
        db.Index("ix_sessionnotes_session", "session_id"),
        db.Index("ix_sessionnotes_professional", "professional_id"),
        db.Index("ix_sessionnotes_patient", "patient_id"),
        db.Index("ix_sessionnotes_created", "created_at"),
    )

    # Compat (si des templates lisaient end_at)
    @property
    def ended_at(self):
        return getattr(self, "end_at", None)

    def __repr__(self):
        return f"<SessionNote id={self.id} session={self.session_id} pro={self.professional_id}>"


# ======================
# Fichiers partagés / pièces jointes
# ======================
class FileAttachment(db.Model):
    __tablename__ = "file_attachments"

    id = db.Column(db.Integer, primary_key=True)
    file_url = db.Column(db.Text, nullable=False)  # ex: /u/attachments/<name>
    file_name = db.Column(db.String(255))
    content_type = db.Column(db.String(120))
    size_bytes = db.Column(db.Integer)

    owner_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="SET NULL")
    )
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner_user = db.relationship("User", foreign_keys=[owner_user_id], lazy="joined")
    patient = db.relationship("User", foreign_keys=[patient_id], lazy="joined")


# ======================
# Messages (liés à MessageThread)
# ======================
class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(
        db.Integer, db.ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False
    )
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text)
    attachment_id = db.Column(
        db.Integer, db.ForeignKey("file_attachments.id", ondelete="SET NULL")
    )
    audio_url = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    thread = db.relationship("MessageThread", lazy="joined", foreign_keys=[thread_id])
    sender = db.relationship("User", lazy="joined", foreign_keys=[sender_id])
    attachment = db.relationship("FileAttachment", lazy="joined", foreign_keys=[attachment_id])

    __table_args__ = (
        db.Index("ix_messages_thread", "thread_id"),
        db.Index("ix_messages_sender", "sender_id"),
        db.Index("ix_messages_created", "created_at"),
    )


# ======================
# Bibliothèque d’exercices
# ======================
class Exercise(db.Model):
    __tablename__ = "exercises"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    family = db.Column(db.String(120))
    type = db.Column(db.String(60), default="exercice")
    technique = db.Column(db.String(120))

    content_format = db.Column(db.String(30), default="texte")  # 'texte', 'pdf', 'audio', 'video'
    text_content = db.Column(db.Text)
    file_url = db.Column(db.Text)

    visibility = db.Column(db.String(30), default="private")  # 'private' | 'my_patients' | 'public'
    is_approved = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", lazy="joined", foreign_keys=[owner_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_exercises_visibility", "visibility"),
        db.Index("ix_exercises_created", "created_at"),
    )


class ExerciseAssignment(db.Model):
    __tablename__ = "exercise_assignments"

    id = db.Column(db.Integer, primary_key=True)

    # Liens
    exercise_id = db.Column(
        db.Integer, db.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    # Dans ta base, il y a patient_id (vers users) ET patient_user_id NOT NULL
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    patient_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Métadonnées
    status = db.Column(db.String(20), nullable=False, default="active")  # "active" pour matcher tes inserts
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations (facultatives mais pratiques)
    exercise = db.relationship("Exercise", lazy="joined", foreign_keys=[exercise_id])
    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_ex_assign_patient", "patient_id"),
        db.Index("ix_ex_assign_patient_user", "patient_user_id"),
        db.Index("ix_ex_assign_professional", "professional_id"),
        db.Index("ix_ex_assign_status", "status"),
    )

class ExerciseAssignment(db.Model):
    __tablename__ = "exercise_assignments"

    id = db.Column(db.Integer, primary_key=True)
    exercise_id = db.Column(
        db.Integer, db.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    # >>> AJOUTER CETTE LIGNE (aligne avec la base) <<<
    patient_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status = db.Column(db.String(20), default="assigned")  # assigned | done | cancelled
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    exercise = db.relationship("Exercise", lazy="joined", foreign_keys=[exercise_id])
    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_ex_assign_patient", "patient_id"),
        db.Index("ix_ex_assign_professional", "professional_id"),
        db.Index("ix_ex_assign_status", "status"),
    )


# ======================
# Facturation & paiements
# ======================
class Invoice(db.Model):
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)

    status = db.Column(db.String(20), default="issued")  # issued | paid | cancelled
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_invoices_professional", "professional_id"),
        db.Index("ix_invoices_status", "status"),
        db.Index("ix_invoices_issued", "issued_at"),
    )


class Payment(db.Model):
    __tablename__ = "payments"

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(
        db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    method = db.Column(db.String(30), default="cash")  # cash | card | transfer
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="succeeded")  # succeeded | failed | pending
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)

    invoice = db.relationship("Invoice", lazy="joined", foreign_keys=[invoice_id])

    __table_args__ = (
        db.Index("ix_payments_invoice", "invoice_id"),
        db.Index("ix_payments_status", "status"),
        db.Index("ix_payments_paid_at", "paid_at"),
    )


# ======================
# Support & guides
# ======================
class SupportTicket(db.Model):
    __tablename__ = "support_tickets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )

    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)

    status = db.Column(db.String(20), default="open")  # open | closed
    priority = db.Column(db.String(20), default="normal")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_tickets_professional", "professional_id"),
        db.Index("ix_tickets_status", "status"),
        db.Index("ix_tickets_created", "created_at"),
    )


class Guide(db.Model):
    __tablename__ = "guides"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ======================
# Consentements & journaux patients
# ======================
class ConsentLog(db.Model):
    __tablename__ = "consent_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    policy_key = db.Column(db.String(60), nullable=False)
    version = db.Column(db.String(20), default="v1")
    accepted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", lazy="joined", foreign_keys=[user_id])

    __table_args__ = (
        db.Index("ix_consent_user", "user_id"),
        db.Index("ix_consent_policy", "policy_key"),
        db.Index("ix_consent_accepted", "accepted_at"),
    )


class PersonalJournalEntry(db.Model):
    __tablename__ = "personal_journal_entries"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    emotion = db.Column(db.String(60))
    is_shared_with_pro = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])

    __table_args__ = (
        db.Index("ix_pje_patient", "patient_id"),
        db.Index("ix_pje_created", "created_at"),
    )


class TherapyNotebookEntry(db.Model):
    __tablename__ = "therapy_notebook_entries"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL")
    )
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    entry_type = db.Column(db.String(30), default="note")  # note | homework | ...
    title = db.Column(db.String(200))
    content = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", foreign_keys=[patient_id], lazy="joined")
    professional = db.relationship("Professional", foreign_keys=[professional_id], lazy="joined")
    author = db.relationship("User", foreign_keys=[author_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_tne_patient", "patient_id"),
        db.Index("ix_tne_professional", "professional_id"),
        db.Index("ix_tne_created", "created_at"),
    )


class ProfessionalReview(db.Model):
    __tablename__ = "professional_reviews"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False
    )

    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined", foreign_keys=[patient_id])
    professional = db.relationship("Professional", lazy="joined", foreign_keys=[professional_id])

    __table_args__ = (
        db.Index("ix_reviews_professional", "professional_id"),
        db.Index("ix_reviews_patient", "patient_id"),
        db.Index("ix_reviews_created", "created_at"),
    )
