# 🚀 Guide de Déploiement Tighri sur Render.com

Ce guide vous accompagne étape par étape pour déployer votre site Tighri sur Render.com et le rendre accessible au public.

## 📋 Prérequis

- Un compte GitHub (gratuit)
- Un compte Render.com (gratuit)
- Votre projet Tighri prêt (déjà configuré)

## 🎯 Étape 1 : Préparer le projet sur GitHub

### 1.1 Créer un repository GitHub
1. Allez sur [github.com](https://github.com)
2. Cliquez sur "New repository"
3. Nommez-le `tighri-project`
4. Choisissez "Public" ou "Private"
5. Cliquez sur "Create repository"

### 1.2 Uploader votre code
```bash
# Dans votre dossier de projet
git init
git add .
git commit -m "Initial commit - Tighri project"
git branch -M main
git remote add origin https://github.com/VOTRE_USERNAME/tighri-project.git
git push -u origin main
```

## 🌐 Étape 2 : Configurer Render.com

### 2.1 Créer un compte Render.com
1. Allez sur [render.com](https://render.com)
2. Cliquez sur "Get Started"
3. Créez un compte avec votre email
4. Connectez votre compte GitHub

### 2.2 Créer un nouveau service
1. Dans le dashboard Render, cliquez sur "New +"
2. Sélectionnez "Web Service"
3. Connectez votre repository GitHub si pas encore fait
4. Sélectionnez le repository `tighri-project`

## ⚙️ Étape 3 : Configuration du Service

### 3.1 Paramètres de base
- **Name** : `tighri-app` (ou le nom que vous voulez)
- **Environment** : `Python 3`
- **Region** : `Frankfurt (EU Central)` (recommandé pour l'Europe)

### 3.2 Configuration du build
- **Build Command** : `pip install -r requirements.txt`
- **Start Command** : `gunicorn app:mounted_admin`

### 3.3 Variables d'environnement
Render configurera automatiquement :
- `SECRET_KEY` (générée automatiquement)
- `DATABASE_URL` (configurée automatiquement)

## 🗄️ Étape 4 : Configurer la Base de Données

### 4.1 Créer une base PostgreSQL
1. Dans le dashboard Render, cliquez sur "New +"
2. Sélectionnez "PostgreSQL"
3. Nommez-la `tighri-db`
4. Choisissez le plan gratuit
5. Cliquez sur "Create Database"

### 4.2 Connecter la base à votre app
1. Retournez à votre service web
2. Allez dans "Environment"
3. Ajoutez la variable `DATABASE_URL` avec l'URL de votre base PostgreSQL

## 🚀 Étape 5 : Déployer

### 5.1 Premier déploiement
1. Cliquez sur "Create Web Service"
2. Render va automatiquement :
   - Installer les dépendances
   - Démarrer l'application
   - Créer l'URL publique

### 5.2 Initialiser la base de données
Une fois déployé, vous devrez initialiser la base de données :
1. Allez dans votre service web sur Render
2. Cliquez sur "Shell"
3. Tapez : `python init_db.py`

## 🔧 Étape 6 : Configuration Finale

### 6.1 Vérifier le déploiement
- Votre site sera accessible sur : `https://votre-app.onrender.com`
- L'admin sera sur : `https://votre-app.onrender.com/admin`

### 6.2 Identifiants par défaut
- **Admin** : `admin` / `admin123`
- **Email** : `admin@tighri.com`

## 📊 Étape 7 : Monitoring et Maintenance

### 7.1 Surveiller les logs
- Dans le dashboard Render, cliquez sur votre service
- Allez dans l'onglet "Logs"
- Surveillez les erreurs éventuelles

### 7.2 Mettre à jour le site
Pour chaque modification :
```bash
git add .
git commit -m "Update description"
git push origin main
```
Render redéploiera automatiquement !

## 🎯 Fonctionnalités Disponibles

### ✅ Site Principal
- Page d'accueil avec professionnels
- Inscription/Connexion
- Recherche de professionnels
- Réservation de rendez-vous

### ✅ Interface Admin
- Validation des professionnels
- Gestion des utilisateurs
- Statistiques et rapports

### ✅ Base de Données
- PostgreSQL professionnel
- Sauvegarde automatique
- Haute disponibilité

## 🔒 Sécurité

- **HTTPS** automatique
- **Variables d'environnement** sécurisées
- **Base de données** isolée
- **Logs** de sécurité

## 📈 Performance

- **CDN** automatique
- **Cache** intelligent
- **Load balancing** automatique
- **Monitoring** en temps réel

## 🆘 Dépannage

### Problème : Site ne se charge pas
1. Vérifiez les logs dans Render
2. Assurez-vous que `init_db.py` a été exécuté
3. Vérifiez les variables d'environnement

### Problème : Erreur de base de données
1. Vérifiez que PostgreSQL est connecté
2. Relancez `python init_db.py`
3. Vérifiez les permissions

### Problème : Admin inaccessible
1. Vérifiez que l'admin a été créé
2. Essayez de vous reconnecter
3. Vérifiez les logs d'authentification

## 🎉 Félicitations !

Votre site Tighri est maintenant en ligne et accessible au public ! 

**URLs importantes :**
- 🌐 Site principal : `https://votre-app.onrender.com`
- 🔧 Admin : `https://votre-app.onrender.com/admin`
- 📊 Dashboard : Dashboard Render.com

**Prochaines étapes :**
1. Personnalisez le contenu
2. Ajoutez vos propres professionnels
3. Configurez un domaine personnalisé
4. Activez les notifications

---

**Lumia** - Votre plateforme de rendez-vous médicaux en ligne ! 🏥 