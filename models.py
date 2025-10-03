# models.py — contrat-fix étendu (Bureau virtuel & Espace patient)
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
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(30))
    user_type = db.Column(db.String(20), default='patient')  # 'patient' | 'professional' | 'admin'
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

    # backrefs: Professional.specialties / primary_specialty
    def __repr__(self): return f"<Specialty id={self.id} {self.name} cat={self.category or '-'}>"

# Pivot Pro <-> Spécialités secondaires
professional_specialties = db.Table(
    "professional_specialties",
    db.Column("professional_id",
              db.Integer,
              db.ForeignKey("professionals.id", ondelete="CASCADE"),
              primary_key=True),
    db.Column("specialty_id",
              db.Integer,
              db.ForeignKey("specialties.id", ondelete="CASCADE"),
              primary_key=True),
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

# =====================================================================
#                   EXTENSIONS — Bureau virtuel & Espace patient
# =====================================================================

# --------- Patient profile & dossier clinique ----------
class PatientProfile(db.Model):
    __tablename__ = "patient_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Fiche patient (infos générales + préférences)
    first_name = db.Column(db.String(120))
    last_name = db.Column(db.String(120))
    birth_date = db.Column(db.Date)
    language = db.Column(db.String(10))              # 'fr' | 'ar' | 'en' ...
    preferred_contact = db.Column(db.String(20))     # 'phone' | 'email' | 'whatsapp'...
    notes_public = db.Column(db.Text)                # résumé visible au pro (si partagé)
    emergency_contact = db.Column(db.String(160))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("patient_profile", uselist=False, passive_deletes=True), lazy="joined")

    __table_args__ = (
        db.Index("ix_patient_profiles_user", "user_id"),
    )

    def __repr__(self): return f"<PatientProfile user_id={self.user_id}>"

class MedicalHistory(db.Model):
    __tablename__ = "medical_histories"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # user_type='patient'
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL"))

    # Données flexibles : antécédents médicaux/psychologiques, allergies, traitements, diagnostics…
    summary = db.Column(db.Text)           # texte libre
    medications = db.Column(db.Text)       # texte libre ou CSV
    allergies = db.Column(db.Text)
    diagnoses = db.Column(db.Text)
    custom_fields = db.Column(db.Text)     # JSON stringifié si besoin

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_medhist_patient", "patient_id"),
        db.Index("ix_medhist_professional", "professional_id"),
    )

# --------- Séances (indépendantes des RDV si besoin) ----------
class TherapySession(db.Model):
    __tablename__ = "therapy_sessions"
    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    start_at = db.Column(db.DateTime, nullable=False)
    end_at = db.Column(db.DateTime)
    mode = db.Column(db.String(20), default="cabinet")     # 'cabinet' | 'domicile' | 'en_ligne'
    meet_url = db.Column(db.Text)                          # lien Google Meet
    status = db.Column(db.String(20), default="planifie")  # 'planifie' | 'fait' | 'annule' | 'no_show'
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointments.id", ondelete="SET NULL"))

    # Notes rapides visibles au pro
    summary = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")
    appointment = db.relationship("Appointment", lazy="joined")

    __table_args__ = (
        db.Index("ix_sessions_patient", "patient_id"),
        db.Index("ix_sessions_professional", "professional_id"),
        db.Index("ix_sessions_start", "start_at"),
        db.Index("ix_sessions_status", "status"),
    )

class SessionNote(db.Model):
    __tablename__ = "session_notes"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("therapy_sessions.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    visibility = db.Column(db.String(20), default="pro")  # 'pro' | 'patient' (partagée)
    content = db.Column(db.Text, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    session = db.relationship("TherapySession", backref=db.backref("notes", cascade="all, delete-orphan", passive_deletes=True))
    author = db.relationship("User", lazy="joined")

# --------- Pièces jointes (dossier, séance, messages) ----------
class FileAttachment(db.Model):
    __tablename__ = "file_attachments"
    id = db.Column(db.Integer, primary_key=True)

    # Dixit Render Disk + liens externes
    file_url = db.Column(db.Text, nullable=False)       # '/u/profiles/xxx.jpg' ou URL https
    content_type = db.Column(db.String(120))
    file_name = db.Column(db.String(255))
    size_bytes = db.Column(db.Integer)

    owner_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))  # qui a uploadé
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"))      # rattachement patient (facilite la recherche)
    session_id = db.Column(db.Integer, db.ForeignKey("therapy_sessions.id", ondelete="SET NULL"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_user_id], lazy="joined")
    patient = db.relationship("User", foreign_keys=[patient_id], lazy="joined")
    session = db.relationship("TherapySession", lazy="joined")

    __table_args__ = (
        db.Index("ix_attach_patient", "patient_id"),
        db.Index("ix_attach_session", "session_id"),
    )

# --------- Messagerie sécurisée patient <-> pro ----------
class MessageThread(db.Model):
    __tablename__ = "message_threads"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    # options
    is_anonymous = db.Column(db.Boolean, default=False)  # consultation anonyme (pseudo)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_threads_patient_pro", "patient_id", "professional_id", unique=True),
    )

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("message_threads.id", ondelete="CASCADE"), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text)  # texte
    attachment_id = db.Column(db.Integer, db.ForeignKey("file_attachments.id", ondelete="SET NULL"))
    audio_url = db.Column(db.Text)  # message vocal (option)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    thread = db.relationship("MessageThread", backref=db.backref("messages", cascade="all, delete-orphan", passive_deletes=True))
    sender = db.relationship("User", lazy="joined")
    attachment = db.relationship("FileAttachment", lazy="joined")

    __table_args__ = (
        db.Index("ix_messages_thread", "thread_id"),
        db.Index("ix_messages_created_at", "created_at"),
        db.Index("ix_messages_read", "is_read"),
    )

# --------- Carnet thérapeutique collaboratif ----------
class TherapyNotebookEntry(db.Model):
    __tablename__ = "therapy_notebook_entries"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))  # pro ou patient

    entry_type = db.Column(db.String(30), default="note")   # 'note' | 'tache' | 'metaphore' | 'devoir' | 'ressenti'
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    is_checked = db.Column(db.Boolean, default=False)       # pour tâches à cocher
    parent_id = db.Column(db.Integer, db.ForeignKey("therapy_notebook_entries.id", ondelete="SET NULL"))  # versionning/commentaires

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    patient = db.relationship("User", foreign_keys=[patient_id], lazy="joined")
    professional = db.relationship("Professional", lazy="joined")
    author = db.relationship("User", foreign_keys=[author_id], lazy="joined")
    parent = db.relationship("TherapyNotebookEntry", remote_side=[id], lazy="joined")

    __table_args__ = (
        db.Index("ix_notebook_patient", "patient_id"),
        db.Index("ix_notebook_pro", "professional_id"),
        db.Index("ix_notebook_type", "entry_type"),
    )

# --------- Bibliothèque d’exercices & suivi ----------
exercise_specialties = db.Table(
    "exercise_specialties",
    db.Column("exercise_id", db.Integer, db.ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True),
    db.Column("specialty_id", db.Integer, db.ForeignKey("specialties.id", ondelete="CASCADE"), primary_key=True),
    db.Index("ix_exercise_spec_ex", "exercise_id"),
    db.Index("ix_exercise_spec_sp", "specialty_id"),
)

class Exercise(db.Model):
    __tablename__ = "exercises"
    id = db.Column(db.Integer, primary_key=True)

    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))      # pro ou admin qui a créé
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL"))
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Classifications / filtres
    family = db.Column(db.String(120))         # ex: Psychothérapie, Coaching… (mappé sur category de Specialty si utile)
    type = db.Column(db.String(50))            # 'exercice' | 'technique' | 'protocole' | 'fiche'
    technique = db.Column(db.String(120))      # 'CBT' | 'Hypnose' | 'Relaxation' | 'EMDR' | 'Coaching' ...
    content_format = db.Column(db.String(20))  # 'texte' | 'audio' | 'video' | 'pdf'

    # Contenu / médias
    text_content = db.Column(db.Text)
    file_url = db.Column(db.Text)              # PDF / doc
    audio_url = db.Column(db.Text)
    video_url = db.Column(db.Text)

    # Visibilité
    visibility = db.Column(db.String(20), default="private")  # 'private' | 'my_patients' | 'invited' | 'public'
    is_approved = db.Column(db.Boolean, default=False)        # si 'public' => validé admin

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")
    specialties = db.relationship("Specialty", secondary=exercise_specialties, lazy="subquery")

    __table_args__ = (
        db.Index("ix_exercises_title", "title"),
        db.Index("ix_exercises_family", "family"),
        db.Index("ix_exercises_type", "type"),
        db.Index("ix_exercises_technique", "technique"),
        db.Index("ix_exercises_visibility", "visibility"),
    )

class ExerciseAssignment(db.Model):
    __tablename__ = "exercise_assignments"
    id = db.Column(db.Integer, primary_key=True)

    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    status = db.Column(db.String(20), default="assigned")  # 'assigned' | 'in_progress' | 'done'
    due_date = db.Column(db.Date)
    progress_pct = db.Column(db.Integer, default=0)        # 0..100
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    exercise = db.relationship("Exercise", lazy="joined")
    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_assign_patient", "patient_id"),
        db.Index("ix_assign_pro", "professional_id"),
        db.Index("ix_assign_exercise", "exercise_id"),
        db.Index("ix_assign_status", "status"),
    )

class ExerciseProgress(db.Model):
    __tablename__ = "exercise_progress"
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("exercise_assignments.id", ondelete="CASCADE"), nullable=False)
    entry_type = db.Column(db.String(20), default="check")  # 'check' | 'note' | 'emotion'
    content = db.Column(db.Text)
    value = db.Column(db.String(50))                        # échelle, %…
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignment = db.relationship("ExerciseAssignment",
                                 backref=db.backref("progress_entries", cascade="all, delete-orphan", passive_deletes=True),
                                 lazy="joined")

# --------- Facturation & paiements ----------
class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default="MAD")
    status = db.Column(db.String(20), default="draft")       # 'draft' | 'issued' | 'paid' | 'cancelled'
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_at = db.Column(db.DateTime)
    description = db.Column(db.Text)
    pdf_url = db.Column(db.Text)                             # export PDF

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_invoices_patient", "patient_id"),
        db.Index("ix_invoices_pro", "professional_id"),
        db.Index("ix_invoices_status", "status"),
        db.Index("ix_invoices_issued", "issued_at"),
    )

class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False)

    method = db.Column(db.String(30))           # 'cash' | 'card' | 'transfer' | 'other'
    provider = db.Column(db.String(50))         # fournisseur éventuel
    provider_ref = db.Column(db.String(120))
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default="succeeded")  # 'succeeded' | 'failed' | 'pending'
    paid_at = db.Column(db.DateTime, default=datetime.utcnow)

    invoice = db.relationship("Invoice", backref=db.backref("payments", cascade="all, delete-orphan", passive_deletes=True), lazy="joined")

    __table_args__ = (
        db.Index("ix_payments_invoice", "invoice_id"),
        db.Index("ix_payments_status", "status"),
        db.Index("ix_payments_paid_at", "paid_at"),
    )

# --------- Tarifs / programmes ----------
class Tariff(db.Model):
    __tablename__ = "tariffs"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    name = db.Column(db.String(120), nullable=False)   # "Séance individuelle", "Pack 5 séances"
    price = db.Column(db.Float, nullable=False)
    duration_minutes = db.Column(db.Integer, default=45)
    is_pack = db.Column(db.Boolean, default=False)
    sessions_count = db.Column(db.Integer)             # si pack

    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_tariff_pro", "professional_id"),
        db.Index("ix_tariff_name", "name"),
    )

class Program(db.Model):
    __tablename__ = "programs"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float)
    duration_weeks = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_programs_pro", "professional_id"),
        db.Index("ix_programs_title", "title"),
    )

# --------- Journal personnel (patient) ----------
class PersonalJournalEntry(db.Model):
    __tablename__ = "personal_journal_entries"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200))
    content = db.Column(db.Text, nullable=False)
    emotion = db.Column(db.String(50))
    is_shared_with_pro = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")

    __table_args__ = (
        db.Index("ix_journal_patient", "patient_id"),
        db.Index("ix_journal_shared", "is_shared_with_pro"),
    )

# --------- Avis & évaluations ----------
class ProfessionalReview(db.Model):
    __tablename__ = "professional_reviews"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="CASCADE"), nullable=False)

    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text)
    is_public = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_reviews_pro", "professional_id"),
        db.Index("ix_reviews_rating", "rating"),
        db.Index("ix_reviews_public", "is_public"),
    )

# --------- Consentements (charte, RGPD, loi marocaine) ----------
class ConsentLog(db.Model):
    __tablename__ = "consent_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    policy_key = db.Column(db.String(80), nullable=False)   # 'privacy_policy', 'ethic_charter', ...
    version = db.Column(db.String(40))
    accepted_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", lazy="joined")

    __table_args__ = (
        db.Index("ix_consent_user_policy", "user_id", "policy_key"),
    )

# --------- Support / tickets / guides ----------
class SupportTicket(db.Model):
    __tablename__ = "support_tickets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id", ondelete="SET NULL"))

    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    status = db.Column(db.String(20), default="open")       # 'open' | 'in_progress' | 'closed'
    priority = db.Column(db.String(20), default="normal")   # 'low' | 'normal' | 'high'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)

    user = db.relationship("User", lazy="joined")
    professional = db.relationship("Professional", lazy="joined")

    __table_args__ = (
        db.Index("ix_ticket_status", "status"),
        db.Index("ix_ticket_user", "user_id"),
        db.Index("ix_ticket_pro", "professional_id"),
    )

class Guide(db.Model):
    __tablename__ = "guides"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    visibility = db.Column(db.String(20), default="public")  # 'public' | 'pro' | 'patient'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index("ix_guides_visibility", "visibility"),
        db.Index("ix_guides_title", "title"),
    )
