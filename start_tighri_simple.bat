@echo off
title DEMARRAGE SIMPLE TIGHRI
color 0A

echo.
echo ========================================
echo    DEMARRAGE SIMPLE DU SITE TIGHRI
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
echo [3/3] Lancement du serveur principal...
echo.
echo 🚀 Lancement sur http://localhost:5000
echo ⏳ Le serveur va démarrer dans une nouvelle fenêtre...
echo.

start "Tighri Site Principal" cmd /k "venv\Scripts\activate.bat && python app.py"

echo.
echo ========================================
echo    🎯 SERVEUR PRINCIPAL LANCE !
echo ========================================
echo.
echo ✅ Le serveur principal est en cours de démarrage
echo ✅ Attends 10-15 secondes que le serveur démarre
echo ✅ Puis va sur: http://localhost:5000
echo.
echo 💡 Si ça ne marche pas:
echo    1. Vérifie que la fenêtre "Tighri Site Principal" est ouverte
echo    2. Attends que le serveur démarre complètement
echo    3. Rafraîchis la page du navigateur
echo.
echo 🌐 URL: http://localhost:5000
echo.
pause 