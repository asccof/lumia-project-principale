# 🚀 GUIDE DE DÉMARRAGE RAPIDE TIGHRI

## 🚨 **PROBLÈME RÉSOLU : "ERR_CONNECTION_REFUSED"**

Le problème venait du fait que Flask n'était pas installé dans l'environnement virtuel. **C'est maintenant corrigé !**

---

## ✅ **SOLUTION IMMÉDIATE (Utilise ces scripts maintenant) :**

### **1. 🚀 Site Principal (Recommandé en premier) :**
```bash
start_tighri_simple.bat
```
- ✅ **Vérifie automatiquement** que Flask est installé
- ✅ **Installe Flask** si nécessaire
- ✅ **Lance le serveur** sur http://localhost:5000
- ✅ **Ouvre une fenêtre séparée** pour voir les logs

### **2. 🔐 Administration (Après le site principal) :**
```bash
start_admin_simple.bat
```
- ✅ **Lance le serveur admin** sur http://localhost:8080
- ✅ **Connexion :** admin / admin123
- ✅ **Fenêtre séparée** pour les logs admin

---

## 🎯 **ÉTAPES DE DÉMARRAGE (À suivre dans l'ordre) :**

### **Étape 1 : Démarrer le Site Principal**
1. **Double-clique** sur `start_tighri_simple.bat`
2. **Attends 10-15 secondes** que le serveur démarre
3. **Vérifie** que la fenêtre "Tighri Site Principal" est ouverte
4. **Va sur** http://localhost:5000

### **Étape 2 : Démarrer l'Administration**
1. **Double-clique** sur `start_admin_simple.bat`
2. **Attends 10-15 secondes** que le serveur démarre
3. **Vérifie** que la fenêtre "Tighri Admin" est ouverte
4. **Va sur** http://localhost:8080
5. **Connecte-toi** avec admin / admin123

---

## 🔍 **VÉRIFICATION QUE TOUT FONCTIONNE :**

### **✅ Site Principal (http://localhost:5000) :**
- Page d'accueil s'affiche
- Navigation fonctionne
- Professionnels s'affichent
- Pas d'erreur "ERR_CONNECTION_REFUSED"

### **✅ Administration (http://localhost:8080) :**
- Page de connexion s'affiche
- Connexion admin / admin123 fonctionne
- Tableau de bord s'affiche
- Gestion des professionnels disponible

### **✅ Page de Statut (http://localhost:5000/site-status) :**
- Informations système affichées
- Statut des serveurs visible
- Connexion admin affichée

---

## 🛠️ **SI ÇA NE MARCHE TOUJOURS PAS :**

### **Solution 1 : Vérifier l'environnement virtuel**
```bash
venv\Scripts\activate
python -c "import flask; print('Flask OK')"
```

### **Solution 2 : Réinstaller Flask**
```bash
venv\Scripts\activate
pip install flask flask-sqlalchemy flask-login werkzeug
```

### **Solution 3 : Redémarrer complètement**
1. **Fermer toutes les fenêtres** de terminal
2. **Fermer le navigateur**
3. **Attendre 10 secondes**
4. **Relancer** avec `start_tighri_simple.bat`

---

## 📱 **ACCÈS AUX SITES (Après démarrage) :**

### **🌐 Site Principal :**
- **URL :** http://localhost:5000
- **Fonctionnalités :** Accueil, professionnels, réservation

### **🔐 Administration :**
- **URL :** http://localhost:8080
- **Identifiants :** admin / admin123
- **Fonctionnalités :** Gestion, validation, statistiques

### **📊 Page de Statut :**
- **URL :** http://localhost:5000/site-status
- **Fonctionnalités :** Informations système, statut des serveurs

---

## 💡 **CONSEILS IMPORTANTS :**

1. **✅ Utilise les scripts simples** (`start_tighri_simple.bat` et `start_admin_simple.bat`)
2. **✅ Attends toujours 10-15 secondes** que les serveurs démarrent
3. **✅ Vérifie que les fenêtres des serveurs sont ouvertes**
4. **✅ Rafraîchis la page** si nécessaire
5. **✅ Utilise les URLs exactes** (localhost:5000 et localhost:8080)

---

## 🎉 **RÉSULTAT ATTENDU :**

Après avoir suivi ces étapes :
- ✅ **Site principal** : http://localhost:5000 fonctionne parfaitement
- ✅ **Administration** : http://localhost:8080 accessible avec admin/admin123
- ✅ **Plus d'erreur** "ERR_CONNECTION_REFUSED"
- ✅ **Toutes les fonctionnalités** opérationnelles

---

## 🚀 **COMMANDES RAPIDES :**

```bash
# Démarrer le site principal
start_tighri_simple.bat

# Démarrer l'administration
start_admin_simple.bat

# Vérifier Flask
venv\Scripts\activate && python -c "import flask; print('OK')"
```

---

**🎯 Maintenant utilise `start_tighri_simple.bat` et tout devrait fonctionner parfaitement !** 