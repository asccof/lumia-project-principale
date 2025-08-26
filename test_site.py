#!/usr/bin/env python3
"""
Script de test pour vérifier le bon fonctionnement du site Tighri
"""

import requests
import time
from datetime import datetime

def test_site():
    """Teste les fonctionnalités principales du site"""
    
    base_url = "http://localhost:5000"
    admin_url = "http://localhost:8080"
    
    print("🧪 TEST DU SITE TIGHRI")
    print("=" * 50)
    
    # Test 1: Site principal
    print("\n1️⃣ Test du site principal...")
    try:
        response = requests.get(base_url, timeout=5)
        if response.status_code == 200:
            print("✅ Site principal accessible")
        else:
            print(f"❌ Site principal: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Site principal inaccessible: {e}")
        return False
    
    # Test 2: Page des professionnels
    print("\n2️⃣ Test de la page des professionnels...")
    try:
        response = requests.get(f"{base_url}/professionals", timeout=5)
        if response.status_code == 200:
            print("✅ Page des professionnels accessible")
        else:
            print(f"❌ Page des professionnels: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Page des professionnels inaccessible: {e}")
    
    # Test 3: API des professionnels
    print("\n3️⃣ Test de l'API des professionnels...")
    try:
        response = requests.get(f"{base_url}/api/professionals", timeout=5)
        if response.status_code == 200:
            data = response.json()
            if len(data) > 0:
                print(f"✅ API des professionnels: {len(data)} professionnels trouvés")
            else:
                print("⚠️ API des professionnels: Aucun professionnel trouvé")
        else:
            print(f"❌ API des professionnels: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ API des professionnels inaccessible: {e}")
    
    # Test 4: Serveur admin
    print("\n4️⃣ Test du serveur admin...")
    try:
        response = requests.get(admin_url, timeout=5)
        if response.status_code == 200:
            print("✅ Serveur admin accessible")
        else:
            print(f"❌ Serveur admin: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Serveur admin inaccessible: {e}")
    
    # Test 5: Page de connexion admin
    print("\n5️⃣ Test de la page de connexion admin...")
    try:
        response = requests.get(f"{admin_url}/login", timeout=5)
        if response.status_code == 200:
            print("✅ Page de connexion admin accessible")
        else:
            print(f"❌ Page de connexion admin: Erreur {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Page de connexion admin inaccessible: {e}")
    
    # Test 6: Vérification des créneaux disponibles
    print("\n6️⃣ Test des créneaux disponibles...")
    try:
        # Récupérer le premier professionnel
        response = requests.get(f"{base_url}/api/professionals", timeout=5)
        if response.status_code == 200:
            professionals = response.json()
            if professionals:
                prof_id = professionals[0]['id']
                today = datetime.now().strftime('%Y-%m-%d')
                response = requests.get(f"{base_url}/api/professional/{prof_id}/available-slots?date={today}", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if 'available_slots' in data:
                        print(f"✅ Créneaux disponibles: {len(data['available_slots'])} créneaux trouvés")
                    else:
                        print("⚠️ Créneaux disponibles: Pas de créneaux disponibles")
                else:
                    print(f"❌ Créneaux disponibles: Erreur {response.status_code}")
            else:
                print("⚠️ Créneaux disponibles: Aucun professionnel pour tester")
        else:
            print(f"❌ Créneaux disponibles: Impossible de récupérer les professionnels")
    except requests.exceptions.RequestException as e:
        print(f"❌ Créneaux disponibles: Erreur {e}")
    
    print("\n" + "=" * 50)
    print("🎯 TESTS TERMINÉS")
    print("\n📋 Vérifications manuelles à faire:")
    print("   • Ouvrir http://localhost:5000 dans ton navigateur")
    print("   • Tester la navigation entre les pages")
    print("   • Vérifier que les professionnels s'affichent")
    print("   • Tester la réservation de rendez-vous")
    print("   • Ouvrir http://localhost:8080 pour l'admin")
    print("   • Se connecter avec admin / admin123")
    
    return True

if __name__ == '__main__':
    print("⏳ Attendre que les serveurs démarrent...")
    time.sleep(3)  # Attendre 3 secondes pour que les serveurs démarrent
    
    test_site() 