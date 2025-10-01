# models.py — contrat-fix (EXTENDED, compatible et non-destructif)
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

    # backrefs remplis automatiquement par Professional.specialties / primary_specialty
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

    # ✅ Intégration Google Meet (ajout non destructif)
    meet_url = db.Column(db.Text)

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

# =========================================================
# 👇 AJOUTS CONTRAT-FIX : Dossier patient, Messagerie, Carnet
# =========================================================

# Dossier patient : profil enrichi (lié à un User)
class PatientProfile(db.Model):
    __tablename__ = "patient_profiles"
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    language = db.Column(db.String(20))             # ex: 'fr', 'ar', 'en'
    preferences = db.Column(db.Text)                # texte libre
    # Antécédents (structure flexible)
    medical_history_json = db.Column(db.JSON)       # {"allergies": "...", "psych": "...", "custom": {...}}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('patient_profile', uselist=False, passive_deletes=True), lazy='joined')

# Lien Pro ↔ Patient (un patient peut avoir plusieurs pros; un pro plusieurs patients)
class PatientCase(db.Model):
    __tablename__ = "patient_cases"
    id = db.Column(db.Integer, primary_key=True)

    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    # visibilité/anonymat
    is_anonymous = db.Column(db.Boolean, default=False)
    # pseudo affiché côté pro si anonyme
    display_name = db.Column(db.String(120))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship('Professional', backref=db.backref('patient_cases', passive_deletes=True))
    patient_user = db.relationship('User', backref=db.backref('patient_cases', passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('professional_id', 'patient_user_id', name='uq_patient_case_pro_patient'),
        db.Index('ix_patient_cases_pro', 'professional_id'),
        db.Index('ix_patient_cases_patient', 'patient_user_id'),
    )

# Notes de séance (rattachées à un RDV existant)
class SessionNote(db.Model):
    __tablename__ = "session_notes"
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id', ondelete='CASCADE'), nullable=False)
    author_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    content = db.Column(db.Text)  # notes du praticien
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship('Appointment', backref=db.backref('session_notes', passive_deletes=True))
    author_user = db.relationship('User')

# Fichiers liés au patient (ordonnances, rapports, audios, etc.)
class PatientFile(db.Model):
    __tablename__ = "patient_files"
    id = db.Column(db.Integer, primary_key=True)

    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='SET NULL'))
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointments.id', ondelete='SET NULL'))

    filename = db.Column(db.String(255), nullable=False)
    file_url = db.Column(db.Text, nullable=False)    # chemin/URI (UploadRoot)
    mime_type = db.Column(db.String(120))
    sha256 = db.Column(db.String(64))                # contrôle d’intégrité (optionnel)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient_user = db.relationship('User', backref=db.backref('patient_files', passive_deletes=True))
    professional = db.relationship('Professional')
    appointment = db.relationship('Appointment')

    __table_args__ = (
        db.Index('ix_patient_files_patient', 'patient_user_id'),
        db.Index('ix_patient_files_professional', 'professional_id'),
        db.Index('ix_patient_files_appointment', 'appointment_id'),
        db.Index('ix_patient_files_created_at', 'created_at'),
    )

# Messagerie : thread pro↔patient
class MessageThread(db.Model):
    __tablename__ = "message_threads"
    id = db.Column(db.Integer, primary_key=True)

    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship('Professional', backref=db.backref('message_threads', passive_deletes=True))
    patient_user = db.relationship('User', backref=db.backref('message_threads', passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('professional_id', 'patient_user_id', name='uq_message_thread_pro_patient'),
        db.Index('ix_message_threads_pro', 'professional_id'),
        db.Index('ix_message_threads_patient', 'patient_user_id'),
    )

class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)

    thread_id = db.Column(db.Integer, db.ForeignKey('message_threads.id', ondelete='CASCADE'), nullable=False)
    sender_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))
    body = db.Column(db.Text)
    attachment_url = db.Column(db.Text)   # fichier/audio optionnel
    is_read = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    thread = db.relationship('MessageThread', backref=db.backref('messages', passive_deletes=True))
    sender = db.relationship('User')

    __table_args__ = (
        db.Index('ix_messages_thread', 'thread_id'),
        db.Index('ix_messages_created_at', 'created_at'),
    )

# Carnet thérapeutique collaboratif
class TherapeuticJournal(db.Model):
    __tablename__ = "therapeutic_journals"
    id = db.Column(db.Integer, primary_key=True)

    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    professional = db.relationship('Professional', backref=db.backref('therapeutic_journals', passive_deletes=True))
    patient_user = db.relationship('User', backref=db.backref('therapeutic_journals', passive_deletes=True))

    __table_args__ = (
        db.UniqueConstraint('professional_id', 'patient_user_id', name='uq_journal_pro_patient'),
        db.Index('ix_ther_journals_pro', 'professional_id'),
        db.Index('ix_ther_journals_patient', 'patient_user_id'),
    )

class JournalEntry(db.Model):
    __tablename__ = "journal_entries"
    id = db.Column(db.Integer, primary_key=True)

    journal_id = db.Column(db.Integer, db.ForeignKey('therapeutic_journals.id', ondelete='CASCADE'), nullable=False)
    author_role = db.Column(db.String(20))   # 'pro' | 'patient'
    title = db.Column(db.String(255))
    content = db.Column(db.Text)             # suggestions, métaphores, ressentis...
    checklist_json = db.Column(db.JSON)      # {"items":[{"label":"...", "done":true/false}, ...]}
    mood_score = db.Column(db.Integer)       # optionnel (0..10)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    journal = db.relationship('TherapeuticJournal', backref=db.backref('entries', passive_deletes=True))

    __table_args__ = (
        db.Index('ix_journal_entries_journal', 'journal_id'),
        db.Index('ix_journal_entries_created_at', 'created_at'),
    )

# =========================================================
# 👇 Bibliothèque d’exercices (filtres familles/spécialités/types/techniques)
# =========================================================

class ExerciseType(db.Model):
    __tablename__ = "exercise_types"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

class Technique(db.Model):
    __tablename__ = "techniques"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)

# Tables de liaison (MTM)
exercise_specialties = db.Table(
    "exercise_specialties",
    db.Column("exercise_id", db.Integer, db.ForeignKey("exercise_items.id", ondelete="CASCADE"), primary_key=True),
    db.Column("specialty_id", db.Integer, db.ForeignKey("specialties.id", ondelete="CASCADE"), primary_key=True),
    db.Index("ix_exspec_exercise", "exercise_id"),
    db.Index("ix_exspec_specialty", "specialty_id"),
)

exercise_types = db.Table(
    "exercise_types_link",
    db.Column("exercise_id", db.Integer, db.ForeignKey("exercise_items.id", ondelete="CASCADE"), primary_key=True),
    db.Column("type_id", db.Integer, db.ForeignKey("exercise_types.id", ondelete="CASCADE"), primary_key=True),
    db.Index("ix_extypes_exercise", "exercise_id"),
    db.Index("ix_extypes_type", "type_id"),
)

exercise_techniques = db.Table(
    "exercise_techniques_link",
    db.Column("exercise_id", db.Integer, db.ForeignKey("exercise_items.id", ondelete="CASCADE"), primary_key=True),
    db.Column("technique_id", db.Integer, db.ForeignKey("techniques.id", ondelete="CASCADE"), primary_key=True),
    db.Index("ix_extech_exercise", "exercise_id"),
    db.Index("ix_extech_technique", "technique_id"),
)

class ExerciseItem(db.Model):
    __tablename__ = "exercise_items"
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)

    # format du support
    format = db.Column(db.String(20))  # "texte"|"audio"|"video"|"pdf"
    content_url = db.Column(db.Text)   # si fichier/asset (UPLOAD_ROOT)
    content_text = db.Column(db.Text)  # si texte brut stocké en DB

    # Propriétaire (pro ou admin)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'))

    # Taxonomie
    # Famille = Specialty.category (on rattache à une famille via un champ string pour éviter un nouveau référentiel)
    family = db.Column(db.String(120))  # cohérent avec specialties.category existant
    # On peut aussi pointer une famille via un id si tu préfères plus tard.

    # Visibilité/partage
    visibility = db.Column(db.String(20), default="private")  # "private"|"my_patients"|"by_invite"|"public_admin"
    is_approved = db.Column(db.Boolean, default=False)        # validation admin si public_admin

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime)  # soft delete

    owner = db.relationship('User')

    specialties = db.relationship(
        "Specialty",
        secondary=exercise_specialties,
        lazy="subquery",
        backref=db.backref("exercise_items", lazy="dynamic")
    )
    types = db.relationship(
        "ExerciseType",
        secondary=exercise_types,
        lazy="subquery",
        backref=db.backref("exercise_items", lazy="dynamic")
    )
    techniques = db.relationship(
        "Technique",
        secondary=exercise_techniques,
        lazy="subquery",
        backref=db.backref("exercise_items", lazy="dynamic")
    )

    __table_args__ = (
        db.Index('ix_exercise_items_title', 'title'),
        db.Index('ix_exercise_items_family', 'family'),
        db.Index('ix_exercise_items_visibility', 'visibility'),
        db.Index('ix_exercise_items_deleted_at', 'deleted_at'),
        db.Index('ix_exercise_items_created_at', 'created_at'),
    )

# Assignation d’un exercice à un patient
class ExerciseAssignment(db.Model):
    __tablename__ = "exercise_assignments"
    id = db.Column(db.Integer, primary_key=True)

    exercise_id = db.Column(db.Integer, db.ForeignKey('exercise_items.id', ondelete='CASCADE'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id', ondelete='CASCADE'), nullable=False)
    patient_user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)

    note_pro = db.Column(db.Text)
    due_date = db.Column(db.DateTime)

    visibility = db.Column(db.String(20), default="assigned")  # réservé à l’assignation
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    exercise = db.relationship('ExerciseItem', backref=db.backref('assignments', passive_deletes=True))
    professional = db.relationship('Professional')
    patient_user = db.relationship('User')

    __table_args__ = (
        db.Index('ix_ex_assign_patient', 'patient_user_id'),
        db.Index('ix_ex_assign_exercise', 'exercise_id'),
        db.Index('ix_ex_assign_professional', 'professional_id'),
        db.UniqueConstraint('exercise_id', 'patient_user_id', 'professional_id', name='uq_exercise_assignment_unique'),
    )

# Suivi de progression d’un exercice
class ExerciseProgress(db.Model):
    __tablename__ = "exercise_progress"
    id = db.Column(db.Integer, primary_key=True)

    assignment_id = db.Column(db.Integer, db.ForeignKey('exercise_assignments.id', ondelete='CASCADE'), nullable=False)
    progress_percent = db.Column(db.Integer, default=0)      # 0..100
    checklist_json = db.Column(db.JSON)                      # {"items":[{"label":"...", "done":true/false}, ...]}
    response_text = db.Column(db.Text)                       # réponses du patient
    response_file_url = db.Column(db.Text)                   # si upload (PDF/audio/etc.)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assignment = db.relationship('ExerciseAssignment', backref=db.backref('progress_entries', passive_deletes=True))

    __table_args__ = (
        db.Index('ix_ex_progress_assignment', 'assignment_id'),
        db.Index('ix_ex_progress_created_at', 'created_at'),
    )
