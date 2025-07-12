@echo off
echo 🌟 Lumia - Lancement automatique des serveurs
echo ==================================================

REM Arrêter tous les processus Python existants
taskkill /f /im python.exe >nul 2>&1

REM Attendre un peu
timeout /t 2 /nobreak >nul

echo 🚀 Activation de l'environnement virtuel...
call venv\Scripts\activate.bat

echo ✅ Environnement virtuel activé
echo.

echo 🌐 Démarrage du serveur principal sur http://localhost:5000
start "Lumia - Serveur Principal" cmd /k "venv\Scripts\activate.bat && python app.py"

echo 🔧 Démarrage du serveur d'administration sur http://localhost:8080
start "Lumia - Administration" cmd /k "venv\Scripts\activate.bat && python admin_server.py"

echo.
echo 🎉 Serveurs démarrés !
echo ==================================================
echo 🌐 Site principal: http://localhost:5000
echo 🔧 Administration: http://localhost:8080
echo 📧 Connexion admin: admin / admin123
echo ==================================================
echo.
echo 💡 Les serveurs sont maintenant accessibles dans les fenêtres ouvertes
echo 💡 Fermez cette fenêtre quand vous avez fini
echo.
pause 