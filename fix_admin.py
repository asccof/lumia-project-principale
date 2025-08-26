#!/usr/bin/env python3
"""
Script pour corriger le mot de passe de l'administrateur Tighri
"""

import os
import sys
from werkzeug.security import generate_password_hash

# Ajouter le répertoire parent au path pour importer les modèles
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app, db, User

def fix_admin_password():
    """Corrige le mot de passe de l'administrateur"""
    
    with app.app_context():
        print("🔧 CORRECTION DU MOT DE PASSE ADMIN")
        print("=" * 50)
        
        # Vérifier si l'admin existe
        admin = User.query.filter_by(username='admin').first()
        
        if admin:
            print(f"✅ Administrateur trouvé: {admin.username}")
            print(f"📧 Email: {admin.email}")
            print(f"🔑 Ancien hash: {admin.password_hash[:50]}...")
            
            # Générer un nouveau hash pour 'admin123'
            new_password = 'admin123'
            new_hash = generate_password_hash(new_password)
            
            # Mettre à jour le mot de passe
            admin.password_hash = new_hash
            db.session.commit()
            
            print(f"🔑 Nouveau hash généré pour '{new_password}'")
            print(f"✅ Mot de passe mis à jour avec succès!")
            
        else:
            print("❌ Aucun administrateur trouvé")
            print("🔧 Création d'un nouvel administrateur...")
            
            # Créer un nouvel admin
            admin = User(
                username='admin',
                email='admin@tighri.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional'
            )
            
            db.session.add(admin)
            db.session.commit()
            
            print("✅ Nouvel administrateur créé!")
        
        print("\n📋 INFORMATIONS DE CONNEXION:")
        print(f"   • Username: admin")
        print(f"   • Mot de passe: admin123")
        print(f"   • Email: admin@tighri.com")
        print(f"   • Type: Administrateur")
        
        print("\n🚀 Tu peux maintenant te connecter avec:")
        print("   • Username: admin")
        print("   • Mot de passe: admin123")
        
        return True

if __name__ == '__main__':
    try:
        fix_admin_password()
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1) 