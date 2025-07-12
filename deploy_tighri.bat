@echo off
echo ========================================
echo    DEPLOIEMENT TIGHRI SUR RENDER.COM
echo ========================================
echo.

echo [1/5] Preparation du projet...
echo - Verification des fichiers de configuration...
if not exist "render.yaml" (
    echo ERREUR: Fichier render.yaml manquant!
    pause
    exit /b 1
)
if not exist "requirements.txt" (
    echo ERREUR: Fichier requirements.txt manquant!
    pause
    exit /b 1
)
if not exist "Procfile" (
    echo ERREUR: Fichier Procfile manquant!
    pause
    exit /b 1
)
echo ✓ Fichiers de configuration OK

echo.
echo [2/5] Initialisation Git...
git init
git add .
git commit -m "Initial commit - Tighri project ready for deployment"
echo ✓ Code prepare pour GitHub

echo.
echo [3/5] Instructions pour GitHub...
echo.
echo 1. Allez sur https://github.com
echo 2. Creez un nouveau repository nomme "tighri-project"
echo 3. Copiez l'URL de votre repository
echo 4. Tapez la commande suivante (remplacez VOTRE_USERNAME):
echo    git remote add origin https://github.com/VOTRE_USERNAME/tighri-project.git
echo    git push -u origin main
echo.

set /p github_url="Entrez l'URL de votre repository GitHub: "
git remote add origin %github_url%
git push -u origin main

echo.
echo [4/5] Instructions pour Render.com...
echo.
echo 1. Allez sur https://render.com
echo 2. Creez un compte et connectez GitHub
echo 3. Cliquez sur "New +" → "Web Service"
echo 4. Selectionnez votre repository "tighri-project"
echo 5. Render detectera automatiquement la configuration
echo 6. Cliquez sur "Create Web Service"
echo.

echo [5/5] Configuration finale...
echo.
echo Une fois deploye sur Render.com:
echo 1. Allez dans votre service web
echo 2. Cliquez sur "Shell"
echo 3. Tapez: python init_db.py
echo 4. Votre site sera accessible sur: https://votre-app.onrender.com
echo.

echo ========================================
echo    DEPLOIEMENT TERMINE!
echo ========================================
echo.
echo Votre site Tighri sera bientot en ligne!
echo.
pause 