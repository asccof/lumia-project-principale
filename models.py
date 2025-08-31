# models.py — une seule instance SQLAlchemy, aucun Flask() ici
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()  # <— unique instance partagée


# ======================
# Utilisateurs
# ======================
class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    user_type = db.Column(db.String(20), default='patient')  # 'patient' ou 'professional'
    is_admin = db.Column(db.Boolean, default=False)

    # RDV pris par l'utilisateur (patient)
    appointments = db.relationship(
        'Appointment',
        backref='patient',
        lazy='dynamic',
        foreign_keys='Appointment.patient_id'
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} type={self.user_type!r}>"


# ======================
# Professionnels
# ======================
class Professional(db.Model):
    __tablename__ = 'professionals'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    consultation_fee = db.Column(db.Float, default=0.0)
    image_url = db.Column(db.String(255))          # peut contenir le chemin local /media/profiles/xxx.jpg
    specialty = db.Column(db.String(120))
    availability = db.Column(db.String(50), default='disponible')
    consultation_types = db.Column(db.String(120))  # ex: "cabinet,domicile,en_ligne"
    location = db.Column(db.String(120))            # ville (fallback)
    phone = db.Column(db.String(50))
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')  # 'valide', 'en_attente', 'rejete'

    # Champs adresse exacte + géolocalisation (déjà ajoutés via mini-migration dans app.py)
    address = db.Column(db.String(255))  # ex: "12 Rue X, Quartier Y, Casablanca"
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)

    # RDV avec ce pro
    appointments = db.relationship(
        'Appointment',
        backref='professional',
        lazy='dynamic',
        foreign_keys='Appointment.professional_id'
    )

    # Les relations vers liens sociaux et avis sont fournies en backref
    # depuis SocialLink et Review (voir plus bas).

    def __repr__(self) -> str:
        return f"<Professional id={self.id} name={self.name!r} status={self.status!r}>"


# ======================
# Rendez-vous
# ======================
class Appointment(db.Model):
    __tablename__ = 'appointments'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    consultation_type = db.Column(db.String(20))  # 'cabinet' | 'domicile' | 'video' | 'en_ligne'
    status = db.Column(db.String(20), default='en_attente')  # 'confirme', 'en_attente', 'annule'
    notes = db.Column(db.Text)

    def __repr__(self) -> str:
        return f"<Appointment id={self.id} pro={self.professional_id} patient={self.patient_id} status={self.status!r}>"


# ======================
# NOUVEAU — Liens sociaux (avec validation admin)
# ======================
class SocialLink(db.Model):
    """
    Lien social rattaché à un professionnel, soumis par le pro,
    et visible publiquement seulement après validation admin.
    """
    __tablename__ = 'social_links'
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False, index=True)
    platform = db.Column(db.String(30), nullable=False)   # 'facebook' | 'instagram' | 'tiktok' | 'youtube'
    url = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending' | 'approved' | 'rejected'
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    professional = db.relationship(
        'Professional',
        backref=db.backref('social_links', lazy='dynamic', cascade='all, delete-orphan')
    )

    def __repr__(self) -> str:
        return f"<SocialLink id={self.id} pro={self.professional_id} platform={self.platform!r} status={self.status!r}>"


# ======================
# NOUVEAU — Avis & évaluations (avec modération)
# ======================
class Review(db.Model):
    """
    Avis utilisateur sur un professionnel.
    Publié seulement si status == 'approved'.
    """
    __tablename__ = 'reviews'
    id = db.Column(db.Integer, primary_key=True)
    pro_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False)  # 1..5
    comment = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending' | 'approved' | 'rejected'
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    pro = db.relationship(
        'Professional',
        backref=db.backref('reviews', lazy='dynamic', cascade='all, delete-orphan')
    )
    author = db.relationship('User', backref=db.backref('reviews', lazy='dynamic'))

    def __repr__(self) -> str:
        return f"<Review id={self.id} pro={self.pro_id} user={self.user_id} rating={self.rating} status={self.status!r}>"
