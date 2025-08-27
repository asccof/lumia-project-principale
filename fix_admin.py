#!/usr/bin/env python3
"""
Script pour créer/corriger le compte administrateur Tighri.
À lancer depuis Render > Shell :  python fix_admin.py
"""

import os
import sys
from werkzeug.security import generate_password_hash

# Aller au répertoire racine du projet (parent du fichier)
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Importer app et models après avoir corrigé le PYTHONPATH
from app import app
from models import db, User

def fix_admin_password():
    with app.app_context():
        # 1) S'assurer que les tables existent
        db.create_all()

        # 2) Récupérer les creds depuis les variables d'env (sinon défaut)
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@tighri.com")
        admin_plain  = os.environ.get("ADMIN_PASSWORD", "admin123")

        admin = User.query.filter_by(username=admin_username).first()
        if admin:
            print(f"✅ Administrateur trouvé: {admin.username} ({admin.email})")
            admin.password_hash = generate_password_hash(admin_plain)
            db.session.commit()
            print("🔑 Mot de passe mis à jour avec succès.")
        else:
            print("ℹ️ Aucun administrateur avec ce username. Création…")
            admin = User(
                username=admin_username,
                email=admin_email,
                password_hash=generate_password_hash(admin_plain),
                is_admin=True,
                user_type="professional",
            )
            db.session.add(admin)
            db.session.commit()
            print("✅ Administrateur créé.")

        print("\n📋 Identifiants (utilisés/attendus) :")
        print(f"   • Username : {admin_username}")
        print(f"   • Mot de passe : {admin_plain}")
        print(f"   • Email : {admin_email}")

if __name__ == "__main__":
    try:
        fix_admin_password()
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)
