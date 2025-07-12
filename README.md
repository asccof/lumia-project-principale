# 🌟 Tighri - Plateforme de Rendez-vous Médicaux

Une plateforme moderne de prise de rendez-vous pour professionnels de santé et patients.

## 🚀 Fonctionnalités

- **Inscription/Connexion** pour patients et professionnels
- **Recherche de professionnels** par spécialité et localisation
- **Réservation de rendez-vous** en ligne
- **Gestion des disponibilités** pour les professionnels
- **Interface d'administration** complète
- **Système de validation** des professionnels

## 🛠️ Technologies

- **Backend** : Flask, SQLAlchemy, PostgreSQL
- **Frontend** : HTML, CSS, Bootstrap, JavaScript
- **Authentification** : Flask-Login
- **Base de données** : SQLite (dev) / PostgreSQL (prod)

## 📋 Installation Locale

1. **Cloner le projet**
```bash
git clone <repository-url>
cd lumia-project
```

2. **Créer l'environnement virtuel**
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

3. **Installer les dépendances**
```bash
pip install -r requirements.txt
```

4. **Lancer l'application**
```bash
python app.py
```

5. **Lancer l'admin** (nouveau terminal)
```bash
python admin_server.py
```

## 🌐 Déploiement sur Render.com

### Étape 1 : Préparer le projet
- Le projet est déjà configuré pour Render.com
- Fichiers de configuration inclus : `render.yaml`, `Procfile`

### Étape 2 : Créer un compte Render.com
1. Allez sur [render.com](https://render.com)
2. Créez un compte gratuit
3. Connectez votre compte GitHub

### Étape 3 : Déployer
1. Cliquez sur "New +" → "Web Service"
2. Connectez votre repository GitHub
3. Sélectionnez le repository Lumia
4. Render détectera automatiquement la configuration
5. Cliquez sur "Create Web Service"

### Étape 4 : Configuration
- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `gunicorn app:app`
- **Environment Variables** : Configurées automatiquement

## 🔧 Variables d'environnement

- `SECRET_KEY` : Clé secrète Flask (générée automatiquement)
- `DATABASE_URL` : URL PostgreSQL (configurée automatiquement)

## 📊 Accès

- **Site principal** : https://votre-app.onrender.com
- **Admin** : https://votre-app.onrender.com/admin
- **Identifiants admin** : admin / admin123

## 🎯 Fonctionnalités Professionnelles

### Pour les Patients
- Recherche de professionnels
- Réservation de rendez-vous
- Gestion de profil
- Historique des consultations

### Pour les Professionnels
- Gestion des disponibilités
- Validation des rendez-vous
- Profil professionnel
- Tableau de bord

### Pour les Administrateurs
- Validation des professionnels
- Gestion des utilisateurs
- Statistiques et rapports
- Configuration système

## 📞 Support

Pour toute question ou problème, contactez l'équipe de développement.

---

**Tighri** - Simplifiez vos rendez-vous médicaux 🏥 