# models.py — une seule instance SQLAlchemy, aucun Flask() ici
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()  # ← instance unique partagée partout

# =========================
# Utilisateur
# =========================
class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    # 'patient' ou 'professional'
    user_type = db.Column(db.String(20), default='patient', nullable=False, index=True)

    # Accès admin au back-office
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # Téléphone (obligatoire côté formulaires ; nullable en DB pour compat ascendante)
    phone = db.Column(db.String(30))

    # RDV pris par l'utilisateur (patient)
    appointments = db.relationship(
        'Appointment',
        backref='patient',
        lazy='dynamic',
        foreign_keys='Appointment.patient_id'
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} type={self.user_type}>"


# =========================
# Professionnel
# =========================
class Professional(db.Model):
    __tablename__ = 'professionals'

    id = db.Column(db.Integer, primary_key=True)

    # Infos principales
    name = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text)
    specialty = db.Column(db.String(120), index=True)

    # Tarifs / visuels
    consultation_fee = db.Column(db.Float, default=0.0)
    image_url = db.Column(db.String(255))  # peut contenir /media/profiles/<fichier>.jpg

    # Disponibilité & types de consultation
    availability = db.Column(db.String(50), default='disponible')  # ex: 'disponible' / 'indisponible'
    consultation_types = db.Column(db.String(120))  # ex: "cabinet,domicile,en_ligne"

    # Localisation (fallback ville) + téléphone d’affichage
    location = db.Column(db.String(120), index=True)  # ville (fallback)
    phone = db.Column(db.String(50))

    # Expérience & statut de validation
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente', index=True)  # 'valide' | 'en_attente' | 'rejete'

    # Adresse exacte + géolocalisation (ajoutés par mini-migrations)
    address = db.Column(db.String(255))  # ex: "12 Rue X, Quartier Y, Casablanca"
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # RDV liés à ce professionnel
    appointments = db.relationship(
        'Appointment',
        backref='professional',
        lazy='dynamic',
        foreign_keys='Appointment.professional_id'
    )

    # Si souhaité plus tard, on pourra activer ces relations (définies dans app.py) :
    # availabilities = db.relationship('ProfessionalAvailability', backref='professional', lazy='dynamic')
    # unavailable_slots = db.relationship('UnavailableSlot', backref='professional', lazy='dynamic')

    def __repr__(self) -> str:
        return f"<Professional id={self.id} name={self.name!r} status={self.status}>"


# =========================
# Rendez-vous
# =========================
class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.Integer, primary_key=True)

    # Liens
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False, index=True)

    # Détail
    appointment_date = db.Column(db.DateTime, nullable=False, index=True)
    consultation_type = db.Column(db.String(20))  # 'cabinet' | 'domicile' | 'video' | 'en_ligne'
    status = db.Column(db.String(20), default='en_attente', index=True)  # 'confirme' | 'en_attente' | 'annule'
    notes = db.Column(db.Text)

    def __repr__(self) -> str:
        return f"<Appointment id={self.id} pro={self.professional_id} patient={self.patient_id} {self.status}>"
