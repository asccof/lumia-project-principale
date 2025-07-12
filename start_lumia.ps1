# Script PowerShell pour démarrer Lumia
Write-Host "🌟 Lumia - Lancement automatique des serveurs" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# Arrêter tous les processus Python existants
Get-Process -Name "python" -ErrorAction SilentlyContinue | Stop-Process -Force

# Attendre un peu
Start-Sleep -Seconds 2

Write-Host "🚀 Activation de l'environnement virtuel..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"

Write-Host "✅ Environnement virtuel activé" -ForegroundColor Green
Write-Host ""

Write-Host "🌐 Démarrage du serveur principal sur http://localhost:5000" -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '.\venv\Scripts\Activate.ps1'; python app.py" -WindowStyle Normal

Write-Host "🔧 Démarrage du serveur d'administration sur http://localhost:8080" -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "& '.\venv\Scripts\Activate.ps1'; python admin_server.py" -WindowStyle Normal

Write-Host ""
Write-Host "🎉 Serveurs démarrés !" -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "🌐 Site principal: http://localhost:5000" -ForegroundColor White
Write-Host "🔧 Administration: http://localhost:8080" -ForegroundColor White
Write-Host "📧 Connexion admin: admin / admin123" -ForegroundColor White
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 Les serveurs sont maintenant accessibles dans les fenêtres ouvertes" -ForegroundColor Yellow
Write-Host "💡 Appuyez sur une touche pour fermer cette fenetre" -ForegroundColor Yellow
Write-Host ""

Read-Host "Appuyez sur Entrée pour continuer" 