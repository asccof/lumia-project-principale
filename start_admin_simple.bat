@echo off
title DEMARRAGE ADMIN TIGHRI
color 0B

echo.
echo ========================================
echo    DEMARRAGE ADMIN TIGHRI
echo ========================================
echo.

echo [1/3] Activation de l'environnement virtuel...
call venv\Scripts\activate.bat
echo ✅ Environnement virtuel activé

echo.
echo [2/3] Vérification de Flask...
python -c "import flask; print('✅ Flask OK - Version:', flask.__version__)"
if errorlevel 1 (
    echo ❌ Flask non installé, installation...
    pip install flask flask-sqlalchemy flask-login werkzeug
    echo ✅ Flask installé
)

echo.
echo [3/3] Lancement du serveur admin...
echo.
echo 🔐 Lancement sur http://localhost:8080
echo ⏳ Le serveur admin va démarrer dans une nouvelle fenêtre...
echo.

start "Tighri Admin" cmd /k "venv\Scripts\activate.bat && python admin_server.py"

echo.
echo ========================================
echo    🔐 SERVEUR ADMIN LANCE !
echo ========================================
echo.
echo ✅ Le serveur admin est en cours de démarrage
echo ✅ Attends 10-15 secondes que le serveur démarre
echo ✅ Puis va sur: http://localhost:8080
echo.
echo 📋 Connexion admin:
echo    • Username: admin
echo    • Mot de passe: admin123
echo.
echo 💡 Si ça ne marche pas:
echo    1. Vérifie que la fenêtre "Tighri Admin" est ouverte
echo    2. Attends que le serveur démarre complètement
echo    3. Rafraîchis la page du navigateur
echo.
echo 🔐 URL: http://localhost:8080
echo.
pause 