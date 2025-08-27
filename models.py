# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = "users"   # pas "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    user_type = db.Column(db.String(20), default='patient')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    is_admin = db.Column(db.Boolean, default=False)

class Professional(db.Model):
    __tablename__ = "professionals"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    consultation_fee = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200))
    specialty = db.Column(db.String(50), nullable=False)
    availability = db.Column(db.String(100), default='disponible')
    consultation_types = db.Column(db.String(100), default='cabinet')
    location = db.Column(db.String(100), default='Casablanca')
    phone = db.Column(db.String(20), default='+212 6 XX XX XX XX')
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='en_attente')
    consultation_type = db.Column(db.String(20), default='cabinet')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # relations
    patient = db.relationship('User', foreign_keys=[patient_id], backref='appointments_as_patient')
    professional = db.relationship('Professional', foreign_keys=[professional_id], backref='appointments')
