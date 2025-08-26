@echo off
title DEMARRAGE OPTIMISE TIGHRI
color 0A

echo.
echo ========================================
echo    DEMARRAGE OPTIMISE DU SITE TIGHRI
echo ========================================
echo.

echo [1/4] Activation de l'environnement virtuel...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ❌ Erreur: Impossible d'activer l'environnement virtuel
    pause
    exit /b 1
)
echo ✅ Environnement virtuel activé

echo.
echo [2/4] Vérification de la base de données...
if not exist "tighri.db" (
    echo ⚠️ Base de données non trouvée, initialisation...
    python init_db.py
    if errorlevel 1 (
        echo ❌ Erreur lors de l'initialisation de la base de données
        pause
        exit /b 1
    )
    echo ✅ Base de données initialisée
) else (
    echo ✅ Base de données trouvée
)

echo.
echo [3/4] Lancement des serveurs...
echo.

echo 🚀 Lancement du serveur principal (port 5000)...
start "Tighri Site Principal" cmd /k "venv\Scripts\activate.bat && python app.py"

echo ⏳ Attente du démarrage du serveur principal...
timeout /t 3 /nobreak >nul

echo 🔐 Lancement du serveur admin (port 8080)...
start "Tighri Admin" cmd /k "venv\Scripts\activate.bat && python admin_server.py"

echo ⏳ Attente du démarrage du serveur admin...
timeout /t 3 /nobreak >nul

echo.
echo [4/4] Ouverture du navigateur...
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
echo 💡 Conseil: Garde les fenêtres des serveurs ouvertes
echo    pour voir les logs et détecter d'éventuelles erreurs.
echo.
pause 