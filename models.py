# models.py
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import func

# Une seule instance globale; init_app(app) est fait dans app.py
db = SQLAlchemy()


# ========= USERS =========
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, index=True, nullable=False)
    email = db.Column(db.String(255), unique=True, index=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # "patient" | "professional"
    user_type = db.Column(db.String(32), default="patient", nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    phone = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<User id={self.id} {self.username} type={self.user_type} admin={self.is_admin}>"


# ======== PROFESSIONALS ========
class Professional(db.Model):
    __tablename__ = "professionals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), index=True, nullable=False)
    specialty = db.Column(db.String(255), index=True)
    status = db.Column(db.String(32), default="en_attente", index=True)  # en_attente | valide | rejete

    # coordonnées
    location = db.Column(db.String(255), index=True)   # ville
    address = db.Column(db.String(255))
    phone = db.Column(db.String(64))
    latitude = db.Column(db.Float)     # attendu float/double
    longitude = db.Column(db.Float)

    # présentation / média
    image_url = db.Column(db.Text)     # URL externe ou /media/profiles/xxx.jpg
    description = db.Column(db.Text)

    # pricing / planning
    consultation_fee = db.Column(db.Float)
    consultation_duration_minutes = db.Column(db.Integer, default=45, nullable=False)
    buffer_between_appointments_minutes = db.Column(db.Integer, default=15, nullable=False)
    availability = db.Column(db.String(32), default="disponible")  # disponible | indisponible
    experience_years = db.Column(db.Integer, default=0)
    consultation_types = db.Column(db.String(255))  # "cabinet,en_ligne,domicile"

    # social
    facebook_url = db.Column(db.Text)
    instagram_url = db.Column(db.Text)
    tiktok_url = db.Column(db.Text)
    youtube_url = db.Column(db.Text)
    social_links_approved = db.Column(db.Boolean, default=False, nullable=False)

    # mise en avant
    is_featured = db.Column(db.Boolean, default=False, nullable=False)
    featured_rank = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<Professional id={self.id} name={self.name!r} status={self.status}>"


# ========= APPOINTMENTS =========
class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True, nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id"), index=True, nullable=False)

    appointment_date = db.Column(db.DateTime, index=True, nullable=False)
    consultation_type = db.Column(db.String(32), default="cabinet", nullable=False)  # cabinet | domicile | en_ligne
    status = db.Column(db.String(32), default="en_attente", index=True, nullable=False)  # en_attente | confirme | annule
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    # relations pratiques
    patient = db.relationship("User", backref=db.backref("appointments", lazy="dynamic"), lazy="joined")
    professional = db.relationship("Professional", backref=db.backref("appointments", lazy="dynamic"), lazy="joined")

    def __repr__(self):
        return f"<Appointment id={self.id} pro={self.professional_id} patient={self.patient_id} at={self.appointment_date} status={self.status}>"


# ========= DISPONIBILITES RECURRENTES =========
class ProfessionalAvailabilityWindow(db.Model):
    """
    Table utilisée par app.py sous le nom 'professional_availability'
    avec les champs: day_of_week, start_time, end_time, is_available.
    """
    __tablename__ = "professional_availability"

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id"), index=True, nullable=False)

    # 0 = lundi ... 6 = dimanche (Python weekday())
    day_of_week = db.Column(db.Integer, nullable=False)

    # "HH:MM"
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)

    is_available = db.Column(db.Boolean, default=True, nullable=False)

    professional = db.relationship("Professional", backref=db.backref("availability_windows", lazy="dynamic"))

    def __repr__(self):
        return f"<Availability pro={self.professional_id} d={self.day_of_week} {self.start_time}-{self.end_time} avail={self.is_available}>"


# ========= INDISPONIBILITES PONCTUELLES =========
class UnavailableSlot(db.Model):
    """
    Nom et table attendus par app.py : class UnavailableSlot, table 'unavailable_slots'
    champs: date, start_time, end_time, reason.
    """
    __tablename__ = "unavailable_slots"

    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id"), index=True, nullable=False)

    date = db.Column(db.Date, default=date.today, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)  # "HH:MM"
    end_time = db.Column(db.String(5), nullable=False)    # "HH:MM"
    reason = db.Column(db.String(255))

    professional = db.relationship("Professional", backref=db.backref("unavailable_slots", lazy="dynamic"))

    def __repr__(self):
        return f"<UnavailableSlot pro={self.professional_id} {self.date} {self.start_time}-{self.end_time}>"
