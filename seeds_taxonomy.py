# seeds_taxonomy.py
# ------------------------------------------------------------
# CONTRAT-FIX • Module pure-data (aucun accès DB, aucun import app)
# ------------------------------------------------------------
# Expose:
# - SPECIALTY_FAMILIES: liste de familles -> spécialités (+synonymes)
# - CITY_OBJECTS: liste d'objets villes (name_fr[, name_ar, region, province, kind])
# - ALL_CITIES: liste simple des noms FR (compat anciens templates)
# - ALL_SPECIALTIES: liste simple des noms FR (compat anciens imports)
#
# Le seeder dans app.py lira SPECIALTY_FAMILIES & ALL_CITIES pour insérer
# familles/spécialités/villes manquantes (idempotent).
# ------------------------------------------------------------

# =========================
# 1) TAXONOMIE FAMILLES → SPÉCIALITÉS
# =========================
SPECIALTY_FAMILIES = [
    {
        "name_fr": "Psychologie & Psychothérapie",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Psychologue clinicien", "synonyms_fr": "psychologue;psy"},
            {"name_fr": "Psychologue du travail", "synonyms_fr": "psychologie du travail;organisationnel;QVT"},
            {"name_fr": "Psychologue scolaire", "synonyms_fr": "psychologue de l'éducation"},
            {"name_fr": "Psychothérapeute", "synonyms_fr": "thérapeute;psychopraticien"},
            {"name_fr": "Thérapeute TCC (CBT)", "synonyms_fr": "thérapie cognitivo-comportementale;TCC;CBT"},
            {"name_fr": "Thérapie ACT / Pleine conscience", "synonyms_fr": "acceptation et engagement;mindfulness;ACT"},
            {"name_fr": "Thérapie DBT", "synonyms_fr": "thérapie dialectique;DBT"},
            {"name_fr": "Thérapie des schémas (Schema Therapy)", "synonyms_fr": "schema therapy"},
            {"name_fr": "Thérapeute EMDR", "synonyms_fr": "EMDR;trauma;ESPT;PTSD"},
            {"name_fr": "Thérapeute IFS", "synonyms_fr": "Internal Family Systems;parts"},
            {"name_fr": "Thérapeute de couple", "synonyms_fr": "thérapie de couple"},
            {"name_fr": "Thérapeute familial", "synonyms_fr": "thérapie familiale;systémique"},
            {"name_fr": "Psychanalyste", "synonyms_fr": "psychanalyse"},
            {"name_fr": "Sexologue clinicien", "synonyms_fr": "sexologue;thérapie sexuelle"},
            {"name_fr": "Neuropsychologue", "synonyms_fr": "neuropsy;neuropsychologie"},
            {"name_fr": "Art-thérapeute", "synonyms_fr": "art thérapie;art-therapie"},
            {"name_fr": "Musicothérapeute", "synonyms_fr": "musicothérapie"},
            {"name_fr": "Dramathérapeute", "synonyms_fr": "drama thérapie"},
            {"name_fr": "Thérapeute enfance & adolescent", "synonyms_fr": "enfant;ado;pédiatrique"},
            {"name_fr": "Conseiller en orientation/éducation", "synonyms_fr": "conseiller pédagogique;orientation"},
        ],
    },
    {
        "name_fr": "Psychiatrie & Addictologie",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Psychiatre (adulte)"},
            {"name_fr": "Psychiatre (enfant & adolescent)", "synonyms_fr": "pédopsychiatre"},
            {"name_fr": "Addictologue", "synonyms_fr": "addictions;substances"},
            {"name_fr": "Géronto-psychiatre"},
            {"name_fr": "Intervention de crise", "synonyms_fr": "prévention suicide;crise"},
        ],
    },
    {
        "name_fr": "Langage, Motricité & Neurodéveloppement",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Orthophoniste", "synonyms_fr": "logopède;troubles du langage;orthophonie"},
            {"name_fr": "Psychomotricien", "synonyms_fr": "psychomotricité"},
            {"name_fr": "Ergothérapeute", "synonyms_fr": "ergothérapie;réadaptation;ergo"},
            {"name_fr": "Analyste du comportement (ABA)", "synonyms_fr": "autisme;ABA"},
            {"name_fr": "Spécialiste TSA / TDAH", "synonyms_fr": "autisme;TDAH;neurodéveloppement"},
            {"name_fr": "Orthoptiste", "synonyms_fr": "orthoptie;vision"},
            {"name_fr": "Neurofeedback / Biofeedback", "synonyms_fr": "neurofeedback;biofeedback"},
        ],
    },
    {
        "name_fr": "Coaching & Développement personnel",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Coach de vie (Life coach)"},
            {"name_fr": "Coach exécutif / Leadership", "synonyms_fr": "executive coach;leadership"},
            {"name_fr": "Coach carrière / Emploi / Outplacement"},
            {"name_fr": "Coach scolaire & orientation", "synonyms_fr": "orientation scolaire"},
            {"name_fr": "Coach parental"},
            {"name_fr": "Préparation mentale / Performance"},
            {"name_fr": "Coach bien-être / santé mentale"},
        ],
    },
    {
        "name_fr": "Conseil conjugal, familial & social",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Conseiller conjugal & familial", "synonyms_fr": "conseil conjugal;médiation"},
            {"name_fr": "Médiateur familial"},
            {"name_fr": "Assistant social"},
            {"name_fr": "Éducateur spécialisé"},
            {"name_fr": "Consultant en santé mentale (organisations)"},
        ],
    },
    {
        "name_fr": "Rééducation & Réadaptation",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Kinésithérapeute", "synonyms_fr": "kiné;physiothérapie;rééducation"},
            {"name_fr": "Ostéopathe", "synonyms_fr": "ostéopathie"},
            {"name_fr": "Chiropracteur", "synonyms_fr": "chiropractie"},
        ],
    },
    {
        "name_fr": "Médecines douces & Bien-être",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Sophrologue", "synonyms_fr": "sophrologie;sophro"},
            {"name_fr": "Hypnothérapeute", "synonyms_fr": "hypnose;hypnothérapie"},
            {"name_fr": "Naturopathe", "synonyms_fr": "naturopathie;phytothérapie"},
            {"name_fr": "Réflexologue", "synonyms_fr": "réflexologie plantaire"},
            {"name_fr": "Praticien EFT", "synonyms_fr": "EFT;tapping"},
            {"name_fr": "Praticien PNL", "synonyms_fr": "programmation neuro-linguistique;PNL"},
            {"name_fr": "Yoga thérapeute"},
            {"name_fr": "Massothérapeute", "synonyms_fr": "massage thérapeutique"},
            {"name_fr": "Méditation & Pleine conscience", "synonyms_fr": "mindfulness;méditation"},
            {"name_fr": "Aromathérapie", "synonyms_fr": "huiles essentielles"},
        ],
    },
    {
        "name_fr": "Traditionnel & Culturel (déclaratif)",
        "name_ar": None,
        "specialties": [
            {"name_fr": "Herboriste (conseils)"},
            {"name_fr": "Praticien hijama / cupping"},
            {"name_fr": "Accompagnement spirituel", "synonyms_fr": "conseil spirituel"},
        ],
    },
]

# Alias compat pour anciens imports (liste à plat des noms FR)
ALL_SPECIALTIES = [sp["name_fr"] for fam in SPECIALTY_FAMILIES for sp in fam.get("specialties", [])]


# =========================
# 2) VILLES (élargies)
# =========================
# Tu peux enrichir librement; le seeder app.py ajoutera seulement le manquant.
CITY_OBJECTS = [
    # --- Casablanca-Settat ---
    {"name_fr": "Casablanca", "name_ar": "الدار البيضاء", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "ville"},
    {"name_fr": "Sidi Belyout", "name_ar": "سيدي بليوط", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Anfa", "name_ar": "أنفا", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Aïn Sebaâ", "name_ar": "عين السبع", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Aïn Chock", "name_ar": "عين الشق", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Hay Hassani", "name_ar": "حي الحسني", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Sidi Bernoussi", "name_ar": "سيدي البرنوصي", "region": "Casablanca-Settat", "province": "Préfecture de Casablanca", "kind": "arrondissement"},
    {"name_fr": "Mohammedia", "name_ar": "المحمدية", "region": "Casablanca-Settat", "province": "Préfecture de Mohammedia", "kind": "ville"},
    {"name_fr": "Médiouna", "name_ar": "مديونة", "region": "Casablanca-Settat", "province": "Province de Médiouna", "kind": "ville"},
    {"name_fr": "Nouaceur", "name_ar": "النواصر", "region": "Casablanca-Settat", "province": "Province de Nouaceur", "kind": "ville"},
    {"name_fr": "Bouskoura", "name_ar": "بوسكورة", "region": "Casablanca-Settat", "province": "Province de Nouaceur", "kind": "commune"},
    {"name_fr": "Berrechid", "name_ar": "برشيد", "region": "Casablanca-Settat", "province": "Province de Berrechid", "kind": "ville"},
    {"name_fr": "Settat", "name_ar": "سطات", "region": "Casablanca-Settat", "province": "Province de Settat", "kind": "ville"},
    {"name_fr": "El Jadida", "name_ar": "الجديدة", "region": "Casablanca-Settat", "province": "Province d'El Jadida", "kind": "ville"},
    {"name_fr": "Sidi Bennour", "name_ar": "سيدي بنور", "region": "Casablanca-Settat", "province": "Province de Sidi Bennour", "kind": "ville"},

    # --- Rabat-Salé-Kénitra ---
    {"name_fr": "Rabat", "name_ar": "الرباط", "region": "Rabat-Salé-Kénitra", "province": "Préfecture de Rabat", "kind": "ville"},
    {"name_fr": "Agdal-Ryad", "name_ar": "أكدال الرياض", "region": "Rabat-Salé-Kénitra", "province": "Préfecture de Rabat", "kind": "arrondissement"},
    {"name_fr": "Yacoub El Mansour", "name_ar": "يعقوب المنصور", "region": "Rabat-Salé-Kénitra", "province": "Préfecture de Rabat", "kind": "arrondissement"},
    {"name_fr": "Salé", "name_ar": "سلا", "region": "Rabat-Salé-Kénitra", "province": "Préfecture de Salé", "kind": "ville"},
    {"name_fr": "Skhirate-Témara", "name_ar": "الصخيرات تمارة", "region": "Rabat-Salé-Kénitra", "province": "Préfecture de Skhirate-Témara", "kind": "ville"},
    {"name_fr": "Kénitra", "name_ar": "القنيطرة", "region": "Rabat-Salé-Kénitra", "province": "Province de Kénitra", "kind": "ville"},
    {"name_fr": "Sidi Kacem", "name_ar": "سيدي قاسم", "region": "Rabat-Salé-Kénitra", "province": "Province de Sidi Kacem", "kind": "ville"},
    {"name_fr": "Sidi Slimane", "name_ar": "سيدي سليمان", "region": "Rabat-Salé-Kénitra", "province": "Province de Sidi Slimane", "kind": "ville"},

    # --- Fès-Meknès ---
    {"name_fr": "Fès", "name_ar": "فاس", "region": "Fès-Meknès", "province": "Préfecture de Fès", "kind": "ville"},
    {"name_fr": "Meknès", "name_ar": "مكناس", "region": "Fès-Meknès", "province": "Préfecture de Meknès", "kind": "ville"},
    {"name_fr": "Sefrou", "name_ar": "صفرو", "region": "Fès-Meknès", "province": "Province de Sefrou", "kind": "ville"},
    {"name_fr": "Ifrane", "name_ar": "إفران", "region": "Fès-Meknès", "province": "Province d'Ifrane", "kind": "ville"},
    {"name_fr": "Taza", "name_ar": "تازة", "region": "Fès-Meknès", "province": "Province de Taza", "kind": "ville"},
    {"name_fr": "El Hajeb", "name_ar": "الحاجب", "region": "Fès-Meknès", "province": "Province d'El Hajeb", "kind": "ville"},

    # --- Tanger-Tétouan-Al Hoceïma ---
    {"name_fr": "Tanger", "name_ar": "طنجة", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Préfecture de Tanger-Assilah", "kind": "ville"},
    {"name_fr": "Tétouan", "name_ar": "تطوان", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Province de Tétouan", "kind": "ville"},
    {"name_fr": "M'diq", "name_ar": "المضيق", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Préfecture de M'diq-Fnideq", "kind": "ville"},
    {"name_fr": "Fnideq", "name_ar": "الفنيدق", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Préfecture de M'diq-Fnideq", "kind": "ville"},
    {"name_fr": "Al Hoceïma", "name_ar": "الحسيمة", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Province d'Al Hoceïma", "kind": "ville"},
    {"name_fr": "Larache", "name_ar": "العرائش", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Province de Larache", "kind": "ville"},
    {"name_fr": "Chefchaouen", "name_ar": "شفشاون", "region": "Tanger-Tétouan-Al Hoceïma", "province": "Province de Chefchaouen", "kind": "ville"},

    # --- Marrakech-Safi ---
    {"name_fr": "Marrakech", "name_ar": "مراكش", "region": "Marrakech-Safi", "province": "Préfecture de Marrakech", "kind": "ville"},
    {"name_fr": "Gueliz", "name_ar": "جيليز", "region": "Marrakech-Safi", "province": "Préfecture de Marrakech", "kind": "arrondissement"},
    {"name_fr": "Ménara", "name_ar": "المنارة", "region": "Marrakech-Safi", "province": "Préfecture de Marrakech", "kind": "arrondissement"},
    {"name_fr": "Safi", "name_ar": "آسفي", "region": "Marrakech-Safi", "province": "Province de Safi", "kind": "ville"},
    {"name_fr": "Essaouira", "name_ar": "الصويرة", "region": "Marrakech-Safi", "province": "Province d'Essaouira", "kind": "ville"},
    {"name_fr": "El Kelaa des Sraghna", "name_ar": "قلعة السراغنة", "region": "Marrakech-Safi", "province": "Province d'El Kelaa des Sraghna", "kind": "ville"},
    {"name_fr": "Chichaoua", "name_ar": "شيشاوة", "region": "Marrakech-Safi", "province": "Province de Chichaoua", "kind": "ville"},

    # --- Souss-Massa ---
    {"name_fr": "Agadir", "name_ar": "أكادير", "region": "Souss-Massa", "province": "Préfecture d'Agadir-Ida-Ou-Tanane", "kind": "ville"},
    {"name_fr": "Inezgane", "name_ar": "إنزكان", "region": "Souss-Massa", "province": "Préfecture d'Inezgane-Aït Melloul", "kind": "ville"},
    {"name_fr": "Aït Melloul", "name_ar": "آيت ملول", "region": "Souss-Massa", "province": "Préfecture d'Inezgane-Aït Melloul", "kind": "ville"},
    {"name_fr": "Taroudant", "name_ar": "تارودانت", "region": "Souss-Massa", "province": "Province de Taroudant", "kind": "ville"},
    {"name_fr": "Tiznit", "name_ar": "تيزنيت", "region": "Souss-Massa", "province": "Province de Tiznit", "kind": "ville"},
    {"name_fr": "Taghazout", "name_ar": "تغازوت", "region": "Souss-Massa", "province": "Agadir", "kind": "commune"},
    {"name_fr": "Aourir", "name_ar": "أورير", "region": "Souss-Massa", "province": "Agadir", "kind": "commune"},

    # --- Béni Mellal-Khénifra ---
    {"name_fr": "Béni Mellal", "name_ar": "بني ملال", "region": "Béni Mellal-Khénifra", "province": "Préfecture de Béni Mellal", "kind": "ville"},
    {"name_fr": "Khouribga", "name_ar": "خريبكة", "region": "Béni Mellal-Khénifra", "province": "Province de Khouribga", "kind": "ville"},
    {"name_fr": "Khénifra", "name_ar": "خنيفرة", "region": "Béni Mellal-Khénifra", "province": "Province de Khénifra", "kind": "ville"},
    {"name_fr": "Fquih Ben Salah", "name_ar": "الفقيه بن صالح", "region": "Béni Mellal-Khénifra", "province": "Province de Fquih Ben Salah", "kind": "ville"},

    # --- Drâa-Tafilalet ---
    {"name_fr": "Errachidia", "name_ar": "الرشيدية", "region": "Drâa-Tafilalet", "province": "Province d'Errachidia", "kind": "ville"},
    {"name_fr": "Ouarzazate", "name_ar": "ورزازات", "region": "Drâa-Tafilalet", "province": "Province d'Ouarzazate", "kind": "ville"},
    {"name_fr": "Tinghir", "name_ar": "تنغير", "region": "Drâa-Tafilalet", "province": "Province de Tinghir", "kind": "ville"},
    {"name_fr": "Zagora", "name_ar": "زاكورة", "region": "Drâa-Tafilalet", "province": "Province de Zagora", "kind": "ville"},
    {"name_fr": "Midelt", "name_ar": "ميدلت", "region": "Drâa-Tafilalet", "province": "Province de Midelt", "kind": "ville"},

    # --- Oriental ---
    {"name_fr": "Oujda", "name_ar": "وجدة", "region": "Oriental", "province": "Préfecture d'Oujda-Angad", "kind": "ville"},
    {"name_fr": "Nador", "name_ar": "الناظور", "region": "Oriental", "province": "Province de Nador", "kind": "ville"},
    {"name_fr": "Berkane", "name_ar": "بركان", "region": "Oriental", "province": "Province de Berkane", "kind": "ville"},
    {"name_fr": "Taourirt", "name_ar": "تاوريرت", "region": "Oriental", "province": "Province de Taourirt", "kind": "ville"},
    {"name_fr": "Jerada", "name_ar": "جرادة", "region": "Oriental", "province": "Province de Jerada", "kind": "ville"},
    {"name_fr": "Guercif", "name_ar": "جرسيف", "region": "Oriental", "province": "Province de Guercif", "kind": "ville"},
    {"name_fr": "Driouch", "name_ar": "الدريوش", "region": "Oriental", "province": "Province de Driouch", "kind": "ville"},

    # --- Guelmim-Oued Noun ---
    {"name_fr": "Guelmim", "name_ar": "كلميم", "region": "Guelmim-Oued Noun", "province": "Province de Guelmim", "kind": "ville"},
    {"name_fr": "Sidi Ifni", "name_ar": "سيدي إفني", "region": "Guelmim-Oued Noun", "province": "Province de Sidi Ifni", "kind": "ville"},
    {"name_fr": "Tan-Tan", "name_ar": "طانطان", "region": "Guelmim-Oued Noun", "province": "Province de Tan-Tan", "kind": "ville"},
    {"name_fr": "Assa", "name_ar": "آسا", "region": "Guelmim-Oued Noun", "province": "Province d'Assa-Zag", "kind": "ville"},
    {"name_fr": "Zag", "name_ar": "زاك", "region": "Guelmim-Oued Noun", "province": "Province d'Assa-Zag", "kind": "ville"},

    # --- Laâyoune-Sakia El Hamra ---
    {"name_fr": "Laâyoune", "name_ar": "العيون", "region": "Laâyoune-Sakia El Hamra", "province": "Préfecture de Laâyoune", "kind": "ville"},
    {"name_fr": "Tarfaya", "name_ar": "طرفاية", "region": "Laâyoune-Sakia El Hamra", "province": "Province de Tarfaya", "kind": "ville"},
    {"name_fr": "Boujdour", "name_ar": "بوجدور", "region": "Laâyoune-Sakia El Hamra", "province": "Province de Boujdour", "kind": "ville"},
    {"name_fr": "Smara", "name_ar": "السمارة", "region": "Laâyoune-Sakia El Hamra", "province": "Province d'Es-Semara", "kind": "ville"},

    # --- Dakhla-Oued Ed-Dahab ---
    {"name_fr": "Dakhla", "name_ar": "الداخلة", "region": "Dakhla-Oued Ed-Dahab", "province": "Préfecture d'Oued Ed-Dahab", "kind": "ville"},
    {"name_fr": "Aousserd", "name_ar": "أوسرد", "region": "Dakhla-Oued Ed-Dahab", "province": "Province d'Aousserd", "kind": "ville"},
    {"name_fr": "Bir Anzarane", "name_ar": "بير أنزران", "region": "Dakhla-Oued Ed-Dahab", "province": "Oued Ed-Dahab", "kind": "centre"},
]

# Alias compat: liste à plat des libellés FR
ALL_CITIES = [c["name_fr"] for c in CITY_OBJECTS]
