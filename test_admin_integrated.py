#!/usr/bin/env python3
"""
Script de test pour vérifier que l'admin intégré fonctionne sous /admin
"""

import requests
import time
from datetime import datetime

def test_admin_integrated():
    """Teste l'admin intégré sous /admin"""
    
    base_url = "http://localhost:5000"
    
    print("🧪 TEST DE L'ADMIN INTÉGRÉ TIGHRI")
    print("=" * 50)
    
    # Test 1: Site principal
    print("\n1️⃣ Test du site principal...")
    try:
        response = requests.get(base_url, timeout=5)
        if response.status_code == 200:
            print("✅ Site principal accessible")
        else:
            print(f"❌ Site principal: Erreur {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Site principal inaccessible: {e}")
        return False
    
    # Test 2: Page admin intégrée
    print("\n2️⃣ Test de l'admin intégré (/admin)...")
    try:
        response = requests.get(f"{base_url}/admin", timeout=5)
        if response.status_code == 200:
            print("✅ Admin intégré accessible sur /admin")
        else:
            print(f"❌ Admin intégré: Erreur {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Admin intégré inaccessible: {e}")
        return False
    
    # Test 3: Page de connexion admin
    print("\n3️⃣ Test de la page de connexion admin...")
    try:
        response = requests.get(f"{base_url}/admin/login", timeout=5)
        if response.status_code == 200:
            print("✅ Page de connexion admin accessible")
        else:
            print(f"❌ Page de connexion admin: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Page de connexion admin inaccessible: {e}")
    
    # Test 4: Vérification des routes admin
    print("\n4️⃣ Test des routes admin principales...")
    admin_routes = [
        "/admin",
        "/admin/login", 
        "/admin/dashboard"
    ]
    
    for route in admin_routes:
        try:
            response = requests.get(f"{base_url}{route}", timeout=5)
            if response.status_code == 200:
                print(f"✅ {route} - Accessible")
            elif response.status_code == 302:  # Redirection (normal pour dashboard sans connexion)
                print(f"✅ {route} - Redirection (normal)")
            else:
                print(f"⚠️ {route} - Statut {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"❌ {route} - Erreur: {e}")
    
    print("\n" + "=" * 50)
    print("🎯 TESTS DE L'ADMIN INTÉGRÉ TERMINÉS")
    print("\n📋 Vérifications manuelles à faire:")
    print("   • Ouvrir http://localhost:5000 (site principal)")
    print("   • Ouvrir http://localhost:5000/admin (admin intégré)")
    print("   • Vérifier que l'admin est accessible sous /admin")
    print("   • Se connecter avec admin / admin123")
    print("   • Tester la navigation entre site principal et admin")
    
    print("\n🌐 URLs de test:")
    print(f"   • Site principal: {base_url}")
    print(f"   • Admin intégré: {base_url}/admin")
    print(f"   • Connexion admin: {base_url}/admin/login")
    
    return True

if __name__ == '__main__':
    print("⏳ Attendre que le serveur démarre...")
    time.sleep(3)  # Attendre 3 secondes pour que le serveur démarre
    
    test_admin_integrated() 