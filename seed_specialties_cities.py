# seed_specialties_cities.py
from app import app
from models import db, City, Specialty

CITIES = [
    "Casablanca","Rabat","Salé","Kénitra","Fès","Meknès","Tanger","Tétouan",
    "Marrakech","Agadir","Oujda","Nador","Laâyoune","Dakhla"
]

SPECIALTIES = [
    "Psychologue clinicien","Psychothérapeute TCC","Thérapeute familial & conjugal",
    "Hypnothérapeute","Thérapeute EMDR","Consultant psychologique",
    "Coach-thérapeute (intégratif)","Coach de vie","Coach parental",
    "Orthophoniste","Art-thérapeute","Sophrologue"
]

with app.app_context():
    created_c = 0
    for name in CITIES:
        if not City.query.filter_by(name=name).first():
            db.session.add(City(name=name)); created_c += 1

    created_s = 0
    for name in SPECIALTIES:
        if not Specialty.query.filter_by(name=name).first():
            db.session.add(Specialty(name=name)); created_s += 1

    db.session.commit()
    print(f"Seed OK — Cities+{created_c}, Specialties+{created_s}")
