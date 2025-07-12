from app import app, db, User, Product
from werkzeug.security import generate_password_hash
from datetime import datetime

def reset_database():
    with app.app_context():
        # Supprimer toutes les tables
        db.drop_all()
        print("🗑️  Tables supprimées")
        
        # Recréer toutes les tables
        db.create_all()
        print("🗄️  Tables recréées")
        
        # Créer l'admin
        admin = User(
            username='admin',
            email='admin@lumia.ma',
            password_hash=generate_password_hash('admin123'),
            user_type='admin',
            is_admin=True,
            created_at=datetime.utcnow()
        )
        db.session.add(admin)
        
        # Créer des professionnels
        prof1 = User(
            username='driss_helali',
            email='driss.helali@lumia.ma',
            password_hash=generate_password_hash('password123'),
            user_type='professional',
            is_admin=False,
            created_at=datetime.utcnow()
        )
        db.session.add(prof1)
        
        prof2 = User(
            username='nada_helali',
            email='nada.helali@lumia.ma',
            password_hash=generate_password_hash('password123'),
            user_type='professional',
            is_admin=False,
            created_at=datetime.utcnow()
        )
        db.session.add(prof2)
        
        # Créer les produits (professionnels)
        product1 = Product(
            name='Driss Helali',
            description='Psychologue clinicien spécialisé en thérapie cognitive et comportementale avec 15 ans d\'expérience.',
            price=0.0,
            category='Psychologue Clinicien',
            consultation_types='home,office,video',
            location='Casablanca',
            phone='+212 6 12 34 56 78',
            image_url='https://via.placeholder.com/300x200/8B5CF6/FFFFFF?text=Driss+Helali',
            created_at=datetime.utcnow()
        )
        db.session.add(product1)
        
        product2 = Product(
            name='Nada Helali',
            description='Thérapeute familiale experte en résolution de conflits et accompagnement conjugal.',
            price=0.0,
            category='Thérapeute Familiale',
            consultation_types='home,office',
            location='Rabat',
            phone='+212 6 23 45 67 89',
            image_url='https://via.placeholder.com/300x200/8B5CF6/FFFFFF?text=Nada+Helali',
            created_at=datetime.utcnow()
        )
        db.session.add(product2)
        
        # Sauvegarder
        db.session.commit()
        print("✅ Base de données réinitialisée !")
        print("📧 Admin: admin / admin123")

if __name__ == "__main__":
    reset_database() 