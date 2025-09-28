# seeds_taxonomy.py
from sqlalchemy import text
from app import app, db

def upsert_city(row):
    db.session.execute(text("""
        INSERT INTO cities (name_fr, name_ar, slug, region, province, kind, is_active)
        VALUES (:name_fr, :name_ar, :slug, :region, :province, :kind, :is_active)
        ON CONFLICT (slug) DO UPDATE SET
          name_fr=EXCLUDED.name_fr, name_ar=EXCLUDED.name_ar,
          region=EXCLUDED.region, province=EXCLUDED.province,
          kind=EXCLUDED.kind, is_active=EXCLUDED.is_active;
    """), row)

def slugify(s): return (s or "").lower().replace(" ", "-").replace("'", "").replace("’","")

# === 2.1 VILLES MAROC (très élargi) ===
CITIES = [
  # --- Casablanca-Settat ---
  {"name_fr":"Casablanca","name_ar":"الدار البيضاء","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"ville"},
  {"name_fr":"Sidi Belyout","name_ar":"سيدي بليوط","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Anfa","name_ar":"أنفا","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Aïn Sebaâ","name_ar":"عين السبع","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Aïn Chock","name_ar":"عين الشق","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Hay Hassani","name_ar":"حي الحسني","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Sidi Bernoussi","name_ar":"سيدي البرنوصي","region":"Casablanca-Settat","province":"Préfecture de Casablanca","kind":"arrondissement"},
  {"name_fr":"Mohammédia","name_ar":"المحمدية","region":"Casablanca-Settat","province":"Préfecture de Mohammédia","kind":"ville"},
  {"name_fr":"Médiouna","name_ar":"مديونة","region":"Casablanca-Settat","province":"Province de Médiouna","kind":"ville"},
  {"name_fr":"Nouaceur","name_ar":"النواصر","region":"Casablanca-Settat","province":"Province de Nouaceur","kind":"ville"},
  {"name_fr":"Bouskoura","name_ar":"بوسكورة","region":"Casablanca-Settat","province":"Province de Nouaceur","kind":"commune"},
  {"name_fr":"Berrechid","name_ar":"برشيد","region":"Casablanca-Settat","province":"Province de Berrechid","kind":"ville"},
  {"name_fr":"Settat","name_ar":"سطات","region":"Casablanca-Settat","province":"Province de Settat","kind":"ville"},
  {"name_fr":"El Jadida","name_ar":"الجديدة","region":"Casablanca-Settat","province":"Province d'El Jadida","kind":"ville"},
  {"name_fr":"Sidi Bennour","name_ar":"سيدي بنور","region":"Casablanca-Settat","province":"Province de Sidi Bennour","kind":"ville"},

  # --- Rabat-Salé-Kénitra ---
  {"name_fr":"Rabat","name_ar":"الرباط","region":"Rabat-Salé-Kénitra","province":"Préfecture de Rabat","kind":"ville"},
  {"name_fr":"Agdal-Ryad","name_ar":"أكدال الرياض","region":"Rabat-Salé-Kénitra","province":"Préfecture de Rabat","kind":"arrondissement"},
  {"name_fr":"Yacoub El Mansour","name_ar":"يعقوب المنصور","region":"Rabat-Salé-Kénitra","province":"Préfecture de Rabat","kind":"arrondissement"},
  {"name_fr":"Salé","name_ar":"سلا","region":"Rabat-Salé-Kénitra","province":"Préfecture de Salé","kind":"ville"},
  {"name_fr":"Skhirate-Témara","name_ar":"الصخيرات تمارة","region":"Rabat-Salé-Kénitra","province":"Préfecture de Skhirate-Témara","kind":"ville"},
  {"name_fr":"Kénitra","name_ar":"القنيطرة","region":"Rabat-Salé-Kénitra","province":"Province de Kénitra","kind":"ville"},
  {"name_fr":"Sidi Kacem","name_ar":"سيدي قاسم","region":"Rabat-Salé-Kénitra","province":"Province de Sidi Kacem","kind":"ville"},
  {"name_fr":"Sidi Slimane","name_ar":"سيدي سليمان","region":"Rabat-Salé-Kénitra","province":"Province de Sidi Slimane","kind":"ville"},

  # --- Fès-Meknès ---
  {"name_fr":"Fès","name_ar":"فاس","region":"Fès-Meknès","province":"Préfecture de Fès","kind":"ville"},
  {"name_fr":"Meknès","name_ar":"مكناس","region":"Fès-Meknès","province":"Préfecture de Meknès","kind":"ville"},
  {"name_fr":"Sefrou","name_ar":"صفرو","region":"Fès-Meknès","province":"Province de Sefrou","kind":"ville"},
  {"name_fr":"Ifrane","name_ar":"إفران","region":"Fès-Meknès","province":"Province d'Ifrane","kind":"ville"},
  {"name_fr":"Taza","name_ar":"تازة","region":"Fès-Meknès","province":"Province de Taza","kind":"ville"},
  {"name_fr":"El Hajeb","name_ar":"الحاجب","region":"Fès-Meknès","province":"Province d'El Hajeb","kind":"ville"},

  # --- Tanger-Tétouan-Al Hoceïma ---
  {"name_fr":"Tanger","name_ar":"طنجة","region":"Tanger-Tétouan-Al Hoceïma","province":"Préfecture de Tanger-Assilah","kind":"ville"},
  {"name_fr":"Tétouan","name_ar":"تطوان","region":"Tanger-Tétouan-Al Hoceïma","province":"Province de Tétouan","kind":"ville"},
  {"name_fr":"M'diq-Fnideq","name_ar":"المضيق الفنيدق","region":"Tanger-Tétouan-Al Hoceïma","province":"Préfecture de M'diq-Fnideq","kind":"ville"},
  {"name_fr":"Al Hoceïma","name_ar":"الحسيمة","region":"Tanger-Tétouan-Al Hoceïma","province":"Province d'Al Hoceïma","kind":"ville"},
  {"name_fr":"Larache","name_ar":"العرائش","region":"Tanger-Tétouan-Al Hoceïma","province":"Province de Larache","kind":"ville"},
  {"name_fr":"Chefchaouen","name_ar":"شفشاون","region":"Tanger-Tétouan-Al Hoceïma","province":"Province de Chefchaouen","kind":"ville"},

  # --- Marrakech-Safi ---
  {"name_fr":"Marrakech","name_ar":"مراكش","region":"Marrakech-Safi","province":"Préfecture de Marrakech","kind":"ville"},
  {"name_fr":"Gueliz","name_ar":"جيليز","region":"Marrakech-Safi","province":"Préfecture de Marrakech","kind":"arrondissement"},
  {"name_fr":"Ménara","name_ar":"المنارة","region":"Marrakech-Safi","province":"Préfecture de Marrakech","kind":"arrondissement"},
  {"name_fr":"Safí","name_ar":"آسفي","region":"Marrakech-Safi","province":"Province de Safi","kind":"ville"},
  {"name_fr":"Essaouira","name_ar":"الصويرة","region":"Marrakech-Safi","province":"Province d'Essaouira","kind":"ville"},
  {"name_fr":"El Kelaa des Sraghna","name_ar":"قلعة السراغنة","region":"Marrakech-Safi","province":"Province d'El Kelaa des Sraghna","kind":"ville"},
  {"name_fr":"Chichaoua","name_ar":"شيشاوة","region":"Marrakech-Safi","province":"Province de Chichaoua","kind":"ville"},

  # --- Souss-Massa ---
  {"name_fr":"Agadir","name_ar":"أكادير","region":"Souss-Massa","province":"Préfecture d'Agadir-Ida-Ou-Tanane","kind":"ville"},
  {"name_fr":"Inezgane-Aït Melloul","name_ar":"إنزكان آيت ملول","region":"Souss-Massa","province":"Préfecture d'Inezgane-Aït Melloul","kind":"ville"},
  {"name_fr":"Taroudant","name_ar":"تارودانت","region":"Souss-Massa","province":"Province de Taroudant","kind":"ville"},
  {"name_fr":"Tiznit","name_ar":"تيزنيت","region":"Souss-Massa","province":"Province de Tiznit","kind":"ville"},

  # --- Béni Mellal-Khénifra ---
  {"name_fr":"Béni Mellal","name_ar":"بني ملال","region":"Béni Mellal-Khénifra","province":"Préfecture de Béni Mellal","kind":"ville"},
  {"name_fr":"Khouribga","name_ar":"خريبكة","region":"Béni Mellal-Khénifra","province":"Province de Khouribga","kind":"ville"},
  {"name_fr":"Khénifra","name_ar":"خنيفرة","region":"Béni Mellal-Khénifra","province":"Province de Khénifra","kind":"ville"},
  {"name_fr":"Fquih Ben Salah","name_ar":"الفقيه بن صالح","region":"Béni Mellal-Khénifra","province":"Province de Fquih Ben Salah","kind":"ville"},

  # --- Drâa-Tafilalet ---
  {"name_fr":"Errachidia","name_ar":"الرشيدية","region":"Drâa-Tafilalet","province":"Province d'Errachidia","kind":"ville"},
  {"name_fr":"Ouarzazate","name_ar":"ورزازات","region":"Drâa-Tafilalet","province":"Province d'Ouarzazate","kind":"ville"},
  {"name_fr":"Tinghir","name_ar":"تنغير","region":"Drâa-Tafilalet","province":"Province de Tinghir","kind":"ville"},
  {"name_fr":"Zagora","name_ar":"زاكورة","region":"Drâa-Tafilalet","province":"Province de Zagora","kind":"ville"},
  {"name_fr":"Midelt","name_ar":"ميدلت","region":"Drâa-Tafilalet","province":"Province de Midelt","kind":"ville"},

  # --- Oriental ---
  {"name_fr":"Oujda","name_ar":"وجدة","region":"Oriental","province":"Préfecture d'Oujda-Angad","kind":"ville"},
  {"name_fr":"Nador","name_ar":"الناظور","region":"Oriental","province":"Province de Nador","kind":"ville"},
  {"name_fr":"Berkane","name_ar":"بركان","region":"Oriental","province":"Province de Berkane","kind":"ville"},
  {"name_fr":"Taourirt","name_ar":"تاوريرت","region":"Oriental","province":"Province de Taourirt","kind":"ville"},
  {"name_fr":"Jerada","name_ar":"جرادة","region":"Oriental","province":"Province de Jerada","kind":"ville"},

  # --- Guelmim-Oued Noun ---
  {"name_fr":"Guelmim","name_ar":"كلميم","region":"Guelmim-Oued Noun","province":"Province de Guelmim","kind":"ville"},
  {"name_fr":"Sidi Ifni","name_ar":"سيدي إفني","region":"Guelmim-Oued Noun","province":"Province de Sidi Ifni","kind":"ville"},
  {"name_fr":"Tan-Tan","name_ar":"طانطان","region":"Guelmim-Oued Noun","province":"Province de Tan-Tan","kind":"ville"},

  # --- Laâyoune-Sakia El Hamra ---
  {"name_fr":"Laâyoune","name_ar":"العيون","region":"Laâyoune-Sakia El Hamra","province":"Préfecture de Laâyoune","kind":"ville"},
  {"name_fr":"Tarfaya","name_ar":"طرفاية","region":"Laâyoune-Sakia El Hamra","province":"Province de Tarfaya","kind":"ville"},
  {"name_fr":"Boujdour","name_ar":"بوجدور","region":"Laâyoune-Sakia El Hamra","province":"Province de Boujdour","kind":"ville"},

  # --- Dakhla-Oued Ed-Dahab ---
  {"name_fr":"Dakhla","name_ar":"الداخلة","region":"Dakhla-Oued Ed-Dahab","province":"Préfecture d'Oued Ed-Dahab","kind":"ville"},
  {"name_fr":"Aousserd","name_ar":"أوسرد","region":"Dakhla-Oued Ed-Dahab","province":"Province d'Aousserd","kind":"ville"},

  # (… + de nombreuses autres communes/arrondissements peuvent être ajoutées via CSV sans toucher le code)
]
for c in CITIES:
    c["slug"] = slugify(f'{c["name_fr"]}-{c["province"] or c["region"]}')
    c.setdefault("is_active", True)
    upsert_city(c)

# === 2.2 FAMILLES/SPÉCIALITÉS (très élargi) ===
def upsert_family(name_fr, name_ar=None, slug=None):
    slug = slug or slugify(name_fr)
    db.session.execute(text("""
      INSERT INTO specialty_families (name_fr, name_ar, slug, is_active)
      VALUES (:name_fr,:name_ar,:slug,TRUE)
      ON CONFLICT (slug) DO UPDATE SET name_fr=EXCLUDED.name_fr, name_ar=EXCLUDED.name_ar, is_active=TRUE;
    """), {"name_fr":name_fr,"name_ar":name_ar,"slug":slug})
    fam_id = db.session.execute(text("SELECT id FROM specialty_families WHERE slug=:s"), {"s":slug}).scalar()
    return fam_id

def upsert_specialty(family_id, name_fr, name_ar=None, synonyms_fr=None, synonyms_ar=None, slug=None):
    slug = slug or slugify(name_fr)
    db.session.execute(text("""
      INSERT INTO specialties (family_id, name_fr, name_ar, slug, synonyms_fr, synonyms_ar, is_active)
      VALUES (:family_id,:name_fr,:name_ar,:slug,:syn_fr,:syn_ar,TRUE)
      ON CONFLICT (slug) DO UPDATE SET
        family_id=EXCLUDED.family_id, name_fr=EXCLUDED.name_fr, name_ar=EXCLUDED.name_ar,
        synonyms_fr=EXCLUDED.synonyms_fr, synonyms_ar=EXCLUDED.synonyms_ar, is_active=TRUE;
    """), {"family_id":family_id,"name_fr":name_fr,"name_ar":name_ar,"slug":slug,
           "syn_fr":synonyms_fr or "", "syn_ar":synonyms_ar or ""})

# Familles principales
fam_psychotherapie   = upsert_family("Psychothérapie", "العلاج النفسي")
fam_psychologie      = upsert_family("Psychologie clinique & neuro", "علم النفس السريري و العصبي")
fam_coaching         = upsert_family("Coaching", "التدريب")
fam_conseil          = upsert_family("Conseil psychologique", "الاستشارة النفسية")
fam_reeducation      = upsert_family("Rééducation & paramédical", "إعادة التأهيل والطب الموازي")
fam_complementaires  = upsert_family("Approches complémentaires & traditionnelles", "مقاربات مكمّلة وتقليدية")
fam_couple_famille   = upsert_family("Couple, famille, parentalité", "العائلة و العلاقات")
fam_enfant_ado       = upsert_family("Enfant & adolescent", "الطفل و المراهق")
fam_travail_orga     = upsert_family("Travail, entreprise & organisation", "العمل و المؤسسة")

# Spécialités — psychothérapie
upsert_specialty(fam_psychotherapie, "TCC (Thérapie Cognitivo-Comportementale)", "العلاج المعرفي السلوكي", "tcc,cognitivo,cbt")
upsert_specialty(fam_psychotherapie, "ACT (Acceptance & Commitment Therapy)", "العلاج بالقبول والالتزام", "act")
upsert_specialty(fam_psychotherapie, "EMDR", "العلاج بحركة العين EMDR", "emdr,trauma,ptsd")
upsert_specialty(fam_psychotherapie, "Thérapie systémique", "العلاج النسقي", "systémique,familiale")
upsert_specialty(fam_psychotherapie, "Psychanalyse", "التحليل النفسي", "freud,klein,lacan")
upsert_specialty(fam_psychotherapie, "Hypnothérapie", "العلاج بالتنويم", "hypnose,hypnothérapie")
upsert_specialty(fam_psychotherapie, "Thérapie humaniste", "العلاج الإنساني", "gestalt,rogerienne,gestalt-thérapie")

# Spécialités — psychologie / neuro
upsert_specialty(fam_psychologie, "Neuropsychologie", "علم النفس العصبي", "bilan neuro,neuropsy")
upsert_specialty(fam_psychologie, "Psychologie clinique", "علم النفس السريري", "clinique")
upsert_specialty(fam_psychologie, "Psychométrie & bilans", "القياس النفسي والروائز", "tests,bilans,qi")

# Spécialités — enfant & ado
upsert_specialty(fam_enfant_ado, "Pédopsychiatrie / Psychologie de l’enfant", "طب نفس الطفل", "enfant,pédiatrique")
upsert_specialty(fam_enfant_ado, "Autisme & TSA", "اضطراب طيف التوحد", "autisme,tsa")
upsert_specialty(fam_enfant_ado, "TDA/H", "فرط الحركة وتشتت الانتباه", "tdah,tdah")
upsert_specialty(fam_enfant_ado, "Dys (dyslexie, dyspraxie, dysorthographie…)", "صعوبات التعلم", "dys,dyslexie,dyscalculie")

# Spécialités — couple / famille
upsert_specialty(fam_couple_famille, "Thérapie de couple", "علاج الأزواج", "couple")
upsert_specialty(fam_couple_famille, "Thérapie familiale", "العلاج العائلي", "famille,systémique")
upsert_specialty(fam_couple_famille, "Guidance parentale", "الإرشاد الأسري", "parentalité,parental")

# Spécialités — travail & organisation
upsert_specialty(fam_travail_orga, "Psychologie du travail / QVT", "علم نفس العمل", "burnout,rps,qvt")
upsert_specialty(fam_travail_orga, "Coaching en entreprise (executive)", "التدريب التنفيذي", "executive,leadership")
upsert_specialty(fam_travail_orga, "Orientation & bilan de carrière", "توجيه و مسار", "orientation,carrière")

# Spécialités — coaching
upsert_specialty(fam_coaching, "Coaching de vie", "التدريب الحياتي", "life coaching")
upsert_specialty(fam_coaching, "Coaching scolaire / étudiant", "التدريب الدراسي", "scolaire,étudiant")
upsert_specialty(fam_coaching, "Coaching parental", "التدريب الأسري", "parental")

# Spécialités — conseil
upsert_specialty(fam_conseil, "Consultant psychologique", "استشاري نفسي", "conseil psy,consultant")
upsert_specialty(fam_conseil, "Conseil conjugal & médiation", "الوساطة الأسرية", "médiation,conjugal")

# Spécialités — rééducation & paramédical (demandées)
upsert_specialty(fam_reeducation, "Orthophoniste", "أخصائي النطق والتخاطب", "orthophonie,logopède,logopédie")
upsert_specialty(fam_reeducation, "Psychomotricien", "أخصائي العلاج النفسي الحركي", "psychomotricité")
upsert_specialty(fam_reeducation, "Kinésithérapeute", "أخصائي الترويض الطبي", "kiné,kinesitherapie,rééducation")
upsert_specialty(fam_reeducation, "Ergothérapeute", "أخصائي العلاج الوظيفي", "ergothérapie,ergo")
upsert_specialty(fam_reeducation, "Orthoptiste", "أخصائي تقويم البصر", "orthoptie")
upsert_specialty(fam_reeducation, "Neurofeedback / Biofeedback", "التغذية الراجعة العصبية", "neurofeedback")

# Spécialités — complémentaires & traditionnelles
upsert_specialty(fam_complementaires, "Sophrologie", "السوفرولوجيا", "sophro")
upsert_specialty(fam_complementaires, "Art-thérapie", "العلاج بالفن", "art thérapie,art-therapie")
upsert_specialty(fam_complementaires, "Musicothérapie", "العلاج بالموسيقى", "musicotherapie")
upsert_specialty(fam_complementaires, "Méditation & Pleine conscience", "التأمل و اليقظة", "mindfulness,meditation")
upsert_specialty(fam_complementaires, "Naturopathie / Phytothérapie", "العلاج بالنباتات", "naturopathie,phyto")
upsert_specialty(fam_complementaires, "Aromathérapie", "العلاج بالزيوت العطرية", "aroma")
upsert_specialty(fam_complementaires, "Thérapies énergétiques (Reiki…)", "العلاج بالطاقة", "reiki,énergétique")

with app.app_context():
    # villes
    for c in CITIES:
        c.setdefault("province", None)
        c.setdefault("kind", "ville")
        upsert_city(c)
    # familles + spécialités : déjà upsert ci-dessus
    db.session.commit()
    print("Seeds villes & spécialités : OK (idempotent)")
