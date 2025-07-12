#!/usr/bin/env python3
"""
Script pour lancer les serveurs Lumia
- Site principal sur le port 5000
- Administration sur le port 8080
"""

import subprocess
import sys
import time
import threading
import os

def run_server(script_name, port, description):
    """Lance un serveur Flask"""
    try:
        print(f"🚀 Démarrage du serveur {description} sur le port {port}...")
        process = subprocess.Popen([sys.executable, script_name], 
                                 stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE,
                                 text=True)
        
        # Attendre un peu pour voir si le serveur démarre correctement
        time.sleep(3)
        
        if process.poll() is None:
            print(f"✅ Serveur {description} démarré avec succès sur http://localhost:{port}")
            return process
        else:
            stdout, stderr = process.communicate()
            print(f"❌ Erreur lors du démarrage du serveur {description}:")
            print(stderr)
            return None
            
    except Exception as e:
        print(f"❌ Erreur lors du lancement du serveur {description}: {e}")
        return None

def main():
    print("🌟 Lumia - Lancement des serveurs")
    print("=" * 50)
    
    # Vérifier que les fichiers existent
    if not os.path.exists('app.py'):
        print("❌ Erreur: app.py introuvable")
        return
    
    if not os.path.exists('admin_server.py'):
        print("❌ Erreur: admin_server.py introuvable")
        return
    
    # Lancer le serveur principal
    main_server = run_server('app.py', 5000, "Site Principal")
    
    if main_server is None:
        print("❌ Impossible de démarrer le serveur principal")
        return
    
    # Lancer le serveur d'administration
    admin_server = run_server('admin_server.py', 8080, "Administration")
    
    if admin_server is None:
        print("❌ Impossible de démarrer le serveur d'administration")
        main_server.terminate()
        return
    
    print("\n" + "=" * 50)
    print("🎉 Tous les serveurs sont démarrés !")
    print("=" * 50)
    print("🌐 Site principal: http://localhost:5000")
    print("🔧 Administration: http://localhost:8080")
    print("📧 Connexion admin: admin / admin123")
    print("=" * 50)
    print("💡 Appuyez sur Ctrl+C pour arrêter tous les serveurs")
    print("=" * 50)
    
    try:
        # Attendre que les utilisateurs appuient sur Ctrl+C
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Arrêt des serveurs...")
        
        if main_server:
            main_server.terminate()
            print("✅ Serveur principal arrêté")
        
        if admin_server:
            admin_server.terminate()
            print("✅ Serveur d'administration arrêté")
        
        print("👋 Au revoir !")

if __name__ == "__main__":
    main() 