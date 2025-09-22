# i18n_ext.py
# i18n minimal, fiable, sans dépendance externe.
from flask import request, redirect, url_for

def init_i18n(app):
    LANG_COOKIE = "site_lang"
    SUPPORTED_LANGS = {"fr": "Français", "en": "English", "ar": "العربية"}

    TRANSLATIONS = {
        "fr": {
            "brand": "Tighri",
            "nav.menu": "Menu",
            "nav.home": "Accueil",
            "nav.pros": "Professionnels",
            "nav.anthecc": "ANTHECC",
            "nav.about": "À propos",
            "nav.contact": "Contact",
            "nav.status": "Statut",
            "auth.login": "Connexion",
            "auth.register": "Inscription",
            "auth.logout": "Déconnexion",
        },
        "en": {
            "brand": "Tighri",
            "nav.menu": "Menu",
            "nav.home": "Home",
            "nav.pros": "Professionals",
            "nav.anthecc": "ANTHECC",
            "nav.about": "About",
            "nav.contact": "Contact",
            "nav.status": "Status",
            "auth.login": "Log in",
            "auth.register": "Sign up",
            "auth.logout": "Log out",
        },
        "ar": {
            "brand": "تيغري",
            "nav.menu": "القائمة",
            "nav.home": "الرئيسية",
            "nav.pros": "المهنيون",
            "nav.anthecc": "ANTHECC",
            "nav.about": "من نحن",
            "nav.contact": "اتصال",
            "nav.status": "الحالة",
            "auth.login": "تسجيل الدخول",
            "auth.register": "إنشاء حساب",
            "auth.logout": "تسجيل الخروج",
        },
    }

    def _normalize_lang(val):
        if not val:
            return "fr"
        v = str(val).strip().lower()
        if v.startswith("fr"):
            return "fr"
        if v.startswith("en"):
            return "en"
        if v.startswith("ar"):
            return "ar"
        return "fr"

    def _detect_lang_from_header():
        al = request.headers.get("Accept-Language", "")
        for part in al.split(","):
            code = part.split(";")[0].strip().lower()
            n = _normalize_lang(code)
            if n in SUPPORTED_LANGS:
                return n
        return "fr"

    def _current_lang():
        v = request.cookies.get(LANG_COOKIE)
        if v:
            return _normalize_lang(v)
        return _detect_lang_from_header()

    @app.context_processor
    def inject_lang():
        lang = _current_lang()
        def t(key, default=None):
            return TRANSLATIONS.get(lang, {}).get(
                key,
                TRANSLATIONS["fr"].get(key, default or key),
            )
        return {
            "t": t,
            "current_lang": lang,
            "current_lang_label": SUPPORTED_LANGS.get(lang, "Français"),
            "text_dir": "rtl" if lang == "ar" else "ltr",
        }

    @app.get("/set-language/<lang>")
    def set_language(lang):
        lang = _normalize_lang(lang)
        resp = redirect(request.referrer or url_for("index"))
        # Cookie valable 1 an
        resp.set_cookie(LANG_COOKIE, lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
        return resp
