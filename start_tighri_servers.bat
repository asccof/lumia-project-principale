 @echo off
cd /d "%~dp0"
echo ========================================
echo    DEMARRAGE DES SERVEURS TIGHRI
echo ========================================
echo.

REM Lancer le site principal dans une fenêtre
start "Tighri Site" cmd /k "venv\Scripts\activate && pip install -r requirements.txt && python app.py"

REM Lancer l'admin dans une autre fenêtre
start "Tighri Admin" cmd /k "venv\Scripts\activate && pip install -r requirements.txt && python admin_server.py"
    
exit 