@echo off
title DEMARRAGE SILENCIEUX TIGHRI
color 0A

echo.
echo ========================================
echo    DEMARRAGE SILENCIEUX DU SITE TIGHRI
echo ========================================
echo.

echo [1/3] Activation de l'environnement virtuel...
call venv\Scripts\activate.bat >nul 2>&1
echo ✅ Environnement virtuel activé

echo.
echo [2/3] Lancement des serveurs en arrière-plan...
echo.

echo 🚀 Lancement du serveur principal (port 5000)...
start "Tighri Site Principal" cmd /k "venv\Scripts\activate.bat >nul 2>&1 && python app.py >nul 2>&1"

echo ⏳ Attente du démarrage du serveur principal...
timeout /t 3 /nobreak >nul

echo 🔐 Lancement du serveur admin (port 8080)...
start "Tighri Admin" cmd /k "venv\Scripts\activate.bat >nul 2>&1 && python admin_server.py >nul 2>&1"

echo ⏳ Attente du démarrage du serveur admin...
timeout /t 3 /nobreak >nul

echo.
echo [3/3] Ouverture du navigateur...
echo.

echo 🌐 Ouverture du site principal...
start http://localhost:5000

echo ⏳ Attente de 2 secondes...
timeout /t 2 /nobreak >nul

echo 🔐 Ouverture de l'administration...
start http://localhost:8080

echo.
echo ========================================
echo    🎯 SITE TIGHRI PRET A L'EMPLOI !
echo ========================================
echo.
echo ✅ Serveur principal: http://localhost:5000
echo ✅ Administration: http://localhost:8080
echo ✅ Connexion admin: admin / admin123
echo.
echo 📋 Fonctionnalités disponibles:
echo    • 8 professionnels avec profils complets
echo    • Système de réservation de rendez-vous
echo    • Gestion des disponibilités
echo    • Administration complète
echo    • Calendriers optimisés pour le travail
echo.
echo 🚀 Le site est maintenant opérationnel !
echo    Tu peux commencer à l'utiliser immédiatement.
echo.
echo 💡 Conseil: Les messages de validation sont maintenant
echo    affichés dans le site web sur la page "Statut"
echo.
echo 🌐 Page de statut: http://localhost:5000/site-status
echo.
pause 