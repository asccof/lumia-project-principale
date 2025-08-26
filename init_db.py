#!/usr/bin/env python3
"""
Script d'initialisation de la base de données Tighri
Crée les tables et ajoute des données d'exemple
"""

import os
import sys
from datetime import datetime, time

# Ajouter le répertoire parent au path pour importer les modèles
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db, User, Professional, ProfessionalAvailability, UnavailableSlot

def init_database():
    """Initialise la base de données avec les tables et données d'exemple"""
    
    with app.app_context():
        print("🗄️  Création des tables de la base de données...")
        db.create_all()
        print("✅ Tables créées avec succès!")
        
        # Vérifier si des utilisateurs existent déjà
        if User.query.first():
            print("⚠️  La base de données contient déjà des données. Suppression des anciennes données...")
            db.drop_all()
            db.create_all()
            print("✅ Base de données réinitialisée!")
        
        print("\n👤 Création de l'utilisateur administrateur...")
            admin = User(
                username='admin',
            email='admin@tighri.com',
            password_hash='pbkdf2:sha256:600000$votre_cle_secrete_ici$hash_placeholder',
                is_admin=True,
            user_type='professional'
            )
            db.session.add(admin)
        db.session.commit()
        print("✅ Administrateur créé: admin / admin123")
        
        print("\n👨‍⚕️  Ajout des professionnels d'exemple...")
        professionals_data = [
            {
                'name': 'Driss Helali',
                'description': "Psychologue clinicien, expert en thérapie cognitive et comportementale. 10 ans d'expérience à Casablanca. Consultations en français et arabe.",
                'specialty': 'Psychologue Clinicien',
                'consultation_fee': 400,
                'image_url': 'https://images.unsplash.com/photo-1559839734-2b71ea197ec2?w=300&h=300&fit=crop&crop=face',
                'location': 'Casablanca',
                'experience_years': 10,
                'status': 'valide'
            },
            {
                'name': 'Nada Helali',
                'description': "Psychologue pour enfants et adolescents. Approche bienveillante et adaptée aux jeunes. Consultations à domicile et en ligne.",
                'specialty': 'Psychologue pour Enfants',
                'consultation_fee': 350,
                'image_url': 'https://images.unsplash.com/photo-1594824475545-9d0c7c4951c5?w=300&h=300&fit=crop&crop=face',
                'location': 'Rabat',
                'experience_years': 7,
                'status': 'valide'
            },
            {
                'name': 'Hatim Heleli',
                'description': "Thérapeute familial et conjugal. Spécialisé dans la résolution de conflits et la communication. Consultations en vidéo et cabinet.",
                'specialty': 'Thérapeute Familial',
                'consultation_fee': 450,
                'image_url': 'https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?w=300&h=300&fit=crop&crop=face',
                'location': 'Marrakech',
                'experience_years': 12,
                'status': 'valide'
            },
            {
                'name': 'Hajar Heleli',
                'description': "Psychologue spécialisée en EMDR et thérapie des traumatismes. Cabinet à Rabat et consultations en ligne.",
                'specialty': 'Psychologue Clinicien',
                'consultation_fee': 500,
                'image_url': 'https://images.unsplash.com/photo-1582750433449-648ed127bb54?w=300&h=300&fit=crop&crop=face',
                'location': 'Rabat',
                'experience_years': 9,
                'status': 'valide'
            },
            {
                'name': 'Loubna Moubine',
                'description': "Coach en développement personnel et gestion du stress. Accompagnement en ligne et en présentiel.",
                'specialty': 'Coach en Développement Personnel',
                'consultation_fee': 300,
                'image_url': 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=300&h=300&fit=crop&crop=face',
                'location': 'Casablanca',
                'experience_years': 6,
                'status': 'valide'
            },
            {
                'name': 'Yassine El Amrani',
                'description': "Thérapeute de couple et sexologue. Consultations en cabinet à Marrakech et en ligne.",
                'specialty': 'Thérapeute de Couple',
                'consultation_fee': 450,
                'image_url': 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=300&h=300&fit=crop&crop=face',
                'location': 'Marrakech',
                'experience_years': 11,
                'status': 'valide'
            },
            {
                'name': 'Imane Berrada',
                'description': "Psychologue clinicienne, spécialisée en gestion des émotions et anxiété. Consultations à Rabat.",
                'specialty': 'Psychologue Clinicien',
                'consultation_fee': 400,
                'image_url': 'https://images.unsplash.com/photo-1511367461989-f85a21fda167?w=300&h=300&fit=crop&crop=face',
                'location': 'Rabat',
                'experience_years': 8,
                'status': 'valide'
            },
            {
                'name': 'Omar El Fassi',
                'description': "Coach professionnel, accompagnement en reconversion et orientation. Disponible en ligne.",
                'specialty': 'Coach en Développement Personnel',
                'consultation_fee': 350,
                'image_url': 'https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=300&h=300&fit=crop&crop=face',
                'location': 'Fès',
                'experience_years': 5,
                'status': 'valide'
            }
        ]
        
        professionals = []
        for data in professionals_data:
            prof = Professional(**data)
            db.session.add(prof)
            professionals.append(prof)
        
        db.session.commit()
        print(f"✅ {len(professionals)} professionnels ajoutés!")
        
        print("\n📅 Configuration des disponibilités par défaut...")
        # Créer des disponibilités par défaut pour chaque professionnel
        for prof in professionals:
            # Lundi à Vendredi: 9h-17h
            for day in range(5):  # 0=Monday, 1=Tuesday, ..., 4=Friday
                availability = ProfessionalAvailability(
                    professional_id=prof.id,
                    day_of_week=day,
                    start_time='09:00',
                    end_time='17:00',
                    is_available=True
                )
                db.session.add(availability)
            
            # Samedi: 9h-13h
            saturday_availability = ProfessionalAvailability(
                professional_id=prof.id,
                day_of_week=5,  # Samedi
                start_time='09:00',
                end_time='13:00',
                is_available=True
            )
            db.session.add(saturday_availability)
        
        db.session.commit()
        print("✅ Disponibilités par défaut configurées!")
        
        print("\n👥 Création d'utilisateurs patients d'exemple...")
        patients_data = [
            {
                'username': 'patient1',
                'email': 'patient1@example.com',
                'password_hash': 'pbkdf2:sha256:600000$votre_cle_secrete_ici$hash_placeholder',
                'user_type': 'patient'
            },
            {
                'username': 'patient2',
                'email': 'patient2@example.com',
                'password_hash': 'pbkdf2:sha256:600000$votre_cle_secrete_ici$hash_placeholder',
                'user_type': 'patient'
            }
        ]
        
        for data in patients_data:
            patient = User(**data)
            db.session.add(patient)
        
        db.session.commit()
        print("✅ Utilisateurs patients créés!")
        
        print("\n🎯 Configuration terminée avec succès!")
        print("\n📋 Récapitulatif:")
        print(f"   • {len(professionals)} professionnels ajoutés")
        print(f"   • Disponibilités configurées (Lun-Ven: 9h-17h, Sam: 9h-13h)")
        print(f"   • Utilisateur admin: admin / admin123")
        print(f"   • Base de données: tighri.db")
        print("\n🚀 Tu peux maintenant lancer les serveurs!")
        print("   • Site principal: python app.py")
        print("   • Admin: python admin_server.py")

if __name__ == '__main__':
    print("=" * 50)
    print("   INITIALISATION DE LA BASE DE DONNÉES TIGHRI")
    print("=" * 50)
    
    try:
    init_database() 
    except Exception as e:
        print(f"❌ Erreur lors de l'initialisation: {e}")
        sys.exit(1) 