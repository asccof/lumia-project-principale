#!/usr/bin/env python3
"""
Script d'initialisation de la base de données pour Tighri
Utilisé pour créer les tables et ajouter les données d'exemple en production
"""

import os
from app import app, db, User, Professional
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_database():
    """Initialise la base de données avec les tables et données d'exemple"""
    
    with app.app_context():
        # Créer toutes les tables
        db.create_all()
        
        print("✅ Tables créées avec succès")
        
        # Vérifier si des utilisateurs existent déjà
        if not User.query.first():
            # Créer l'administrateur par défaut
            admin = User(
                username='admin',
                email='admin@lumia.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional',
                created_at=datetime.utcnow()
            )
            db.session.add(admin)
            print("✅ Administrateur créé : admin / admin123")
        
        # Vérifier si des professionnels existent déjà
        if not Professional.query.first():
            # Ajouter des professionnels d'exemple
            examples = [
                Professional(
                    name='Driss Helali',
                    description="Psychologue clinicien, expert en thérapie cognitive et comportementale. 10 ans d'expérience à Casablanca. Consultations en français et arabe.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=400,
                    image_url='https://images.unsplash.com/photo-1559839734-2b71ea197ec2?w=300&h=300&fit=crop&crop=face',
                    location='Casablanca',
                    experience_years=10,
                    status='valide'
                ),
                Professional(
                    name='Nada Helali',
                    description="Psychologue pour enfants et adolescents. Approche bienveillante et adaptée aux jeunes. Consultations à domicile et en ligne.",
                    specialty='Psychologue pour Enfants',
                    consultation_fee=350,
                    image_url='https://images.unsplash.com/photo-1594824475545-9d0c7c4951c5?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=7,
                    status='valide'
                ),
                Professional(
                    name='Hatim Heleli',
                    description="Thérapeute familial et conjugal. Spécialisé dans la résolution de conflits et la communication. Consultations en vidéo et cabinet.",
                    specialty='Thérapeute Familial',
                    consultation_fee=450,
                    image_url='https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?w=300&h=300&fit=crop&crop=face',
                    location='Marrakech',
                    experience_years=12,
                    status='valide'
                ),
                Professional(
                    name='Hajar Heleli',
                    description="Psychologue spécialisée en EMDR et thérapie des traumatismes. Cabinet à Rabat et consultations en ligne.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=500,
                    image_url='https://images.unsplash.com/photo-1582750433449-648ed127bb54?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=9,
                    status='valide'
                ),
                Professional(
                    name='Loubna Moubine',
                    description="Coach en développement personnel et gestion du stress. Accompagnement en ligne et en présentiel.",
                    specialty='Coach en Développement Personnel',
                    consultation_fee=300,
                    image_url='https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=300&h=300&fit=crop&crop=face',
                    location='Casablanca',
                    experience_years=6,
                    status='valide'
                ),
                Professional(
                    name='Yassine El Amrani',
                    description="Thérapeute de couple et sexologue. Consultations en cabinet à Marrakech et en ligne.",
                    specialty='Thérapeute de Couple',
                    consultation_fee=450,
                    image_url='https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=300&h=300&fit=crop&crop=face',
                    location='Marrakech',
                    experience_years=11,
                    status='valide'
                ),
                Professional(
                    name='Imane Berrada',
                    description="Psychologue clinicienne, spécialisée en gestion des émotions et anxiété. Consultations à Rabat.",
                    specialty='Psychologue Clinicien',
                    consultation_fee=400,
                    image_url='https://images.unsplash.com/photo-1511367461989-f85a21fda167?w=300&h=300&fit=crop&crop=face',
                    location='Rabat',
                    experience_years=8,
                    status='valide'
                ),
                Professional(
                    name='Omar El Fassi',
                    description="Coach professionnel, accompagnement en reconversion et orientation. Disponible en ligne.",
                    specialty='Coach en Développement Personnel',
                    consultation_fee=350,
                    image_url='https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?w=300&h=300&fit=crop&crop=face',
                    location='Fès',
                    experience_years=5,
                    status='valide'
                )
            ]
            
            for prof in examples:
                db.session.add(prof)
            
            print("✅ 8 professionnels d'exemple ajoutés")
        
        # Commit des changements
        db.session.commit()
        print("✅ Base de données initialisée avec succès !")
        print("🌐 Votre site Tighri est prêt pour la production !")

if __name__ == '__main__':
    init_database() 