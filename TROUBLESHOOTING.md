# 🔧 GUIDE DE DÉPANNAGE TIGHRI

## 🚨 **PROBLÈMES COURANTS ET SOLUTIONS**

### **❌ Site principal ne fonctionne pas**

**Symptôme :** Erreur "ModuleNotFoundError: No module named 'flask'"

**Solution :**
1. **Activer l'environnement virtuel :**
   ```bash
   venv\Scripts\activate
   ```

2. **Vérifier que Flask est installé :**
   ```bash
   pip list | findstr flask
   ```

3. **Réinstaller Flask si nécessaire :**
   ```bash
   pip install flask flask-sqlalchemy flask-login werkzeug
   ```

4. **Utiliser le script corrigé :**
   ```bash
   start_tighri_fixed.bat
   ```

---

### **❌ Erreur de base de données**

**Symptôme :** Erreur "no such table" ou "database is locked"

**Solution :**
1. **Arrêter tous les serveurs** (fermer les fenêtres de terminal)
2. **Supprimer la base de données :**
   ```bash
   del tighri.db
   ```
3. **Réinitialiser la base de données :**
   ```bash
   python init_db.py
   ```
4. **Relancer les serveurs :**
   ```bash
   start_tighri_fixed.bat
   ```

---

### **❌ Impossible de se connecter en admin**

**Symptôme :** "Identifiants incorrects ou accès non autorisé"

**Solution :**
1. **Corriger le mot de passe admin :**
   ```bash
   python fix_admin.py
   ```
2. **Utiliser les identifiants :**
   - Username: `admin`
   - Mot de passe: `admin123`
3. **Vérifier l'URL :** http://localhost:8080

---

### **❌ Ports déjà utilisés**

**Symptôme :** "Address already in use" ou "port already in use"

**Solution :**
1. **Fermer tous les processus Python :**
   ```bash
   taskkill /f /im python.exe
   ```
2. **Attendre 10 secondes**
3. **Relancer avec le script corrigé :**
   ```bash
   start_tighri_fixed.bat
   ```

---

## 🚀 **SCRIPTS DE DÉMARRAGE DISPONIBLES**

### **1. Script Principal (Recommandé) :**
```bash
start_tighri_fixed.bat
```
- ✅ **Démarrage complet** avec vérifications
- ✅ **Gestion des erreurs** intégrée
- ✅ **Ouverture automatique** du navigateur

### **2. Script Silencieux :**
```bash
start_tighri_silent.bat
```
- ✅ **Démarrage sans messages** de validation
- ✅ **Serveurs en arrière-plan**
- ✅ **Interface propre**

### **3. Script Original :**
```bash
start_tighri_servers.bat
```
- ✅ **Démarrage manuel** des serveurs
- ✅ **Fenêtres séparées** visibles
- ✅ **Contrôle total**

---

## 🔍 **VÉRIFICATION RAPIDE**

### **Test 1: Vérifier l'environnement**
```bash
venv\Scripts\activate
python -c "import flask; print('Flask OK')"
```

### **Test 2: Vérifier la base de données**
```bash
python init_db.py
```

### **Test 3: Tester le site**
```bash
python test_site.py
```

---

## 📱 **ACCÈS AUX SITES**

### **Site Principal :**
- **URL :** http://localhost:5000
- **Fonctionnalités :** Professionnels, réservation, etc.

### **Administration :**
- **URL :** http://localhost:8080
- **Identifiants :** admin / admin123

### **Page de Statut :**
- **URL :** http://localhost:5000/site-status
- **Fonctionnalités :** Statut des serveurs, informations système

---

## 🎯 **SOLUTION RAPIDE (90% des cas)**

Si rien ne fonctionne, utilisez cette séquence :

1. **Fermer toutes les fenêtres** de terminal
2. **Ouvrir un nouveau terminal** dans le dossier du projet
3. **Exécuter :**
   ```bash
   start_tighri_fixed.bat
   ```

Ce script corrige automatiquement la plupart des problèmes !

---

## 📞 **SUPPORT**

### **Fichiers de diagnostic :**
- `test_site.py` - Tests automatisés du site
- `fix_admin.py` - Correction du mot de passe admin
- `init_db.py` - Réinitialisation de la base de données

### **Logs d'erreur :**
- Vérifier les fenêtres des serveurs pour les messages d'erreur
- Utiliser la page de statut pour diagnostiquer les problèmes

---

**💡 Conseil :** Utilisez toujours `start_tighri_fixed.bat` pour un démarrage fiable ! 