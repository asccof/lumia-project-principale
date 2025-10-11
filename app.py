# app.py — Tighri (contrat fixe + Bureau virtuel & Espace patient)
from __future__ import annotations

import os
import io
import uuid
import secrets
import hashlib
import json
from pathlib import Path
from typing import Optional
from datetime import datetime, date, time as dtime, timedelta
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import requests
from dotenv import load_dotenv
from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response, current_app, make_response, g, abort
)
from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from jinja2 import TemplateNotFound
from sqlalchemy import or_, and_, text, func, case

# === Extensions (db) ===
from extensions import db  # db.init_app(app) sera appelé après config

# -------------------------------------------------------------------
# Environnement
# -------------------------------------------------------------------
load_dotenv()

# -------------------------------------------------------------------
# Constantes / Dossiers
# -------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = UPLOAD_ROOT / "profiles"
ATTACHMENTS_FOLDER = UPLOAD_ROOT / "attachments"  # pièces jointes

ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif"}
ALLOWED_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"} | ALLOWED_IMAGE_EXT
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo

# -------------------------------------------------------------------
# Flask app
# -------------------------------------------------------------------
app = Flask(__name__)

# Jinja helper: has_endpoint("name")
@app.context_processor
def inject_has_endpoint():
    def has_endpoint(name: str) -> bool:
        return name in current_app.view_functions
    return dict(has_endpoint=has_endpoint)

# Sécurité & cookies / sessions
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
    PREFERRED_URL_SCHEME="https",

    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_SECURE=True,        # HTTPS
    SESSION_COOKIE_SAMESITE="Lax",

    REMEMBER_COOKIE_NAME="tighri_remember",
    REMEMBER_COOKIE_DURATION=timedelta(days=60),
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_SAMESITE="Lax",

    UPLOAD_FOLDER=str(UPLOAD_FOLDER),
    MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
)

from flask import session
@app.before_request
def _keep_session_permanent():
    session.permanent = True

# -------------------------------------------------------------------
# DB / SQLAlchemy + psycopg3
# -------------------------------------------------------------------
def _normalize_pg_uri(uri: str) -> str:
    """Normalise une URI Postgres pour SQLAlchemy + psycopg3 et ajoute sslmode=require si manquant."""
    if not uri:
        return uri
    # Heroku/Render fournissent parfois 'postgres://'
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    # Forcer psycopg3
    if uri.startswith("postgresql+psycopg2://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    # sslmode=require si absent
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)
    if parsed.scheme.startswith("postgresql+psycopg") and "sslmode" not in q:
        q["sslmode"] = ["require"]
        uri = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return uri

db_url = (
    os.getenv("SQLALCHEMY_DATABASE_URI")
    or os.getenv("DATABASE_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("DATABASE_URL_INTERNAL")
)
if not db_url:
    raise RuntimeError("Missing DATABASE_URL or SQLALCHEMY_DATABASE_URI environment variable")
db_url = _normalize_pg_uri(db_url)

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    **app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {}),
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "pool_size": 5,
    "max_overflow": 10,
}

# Proxy (Render/Cloudflare)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Initialiser la DB après config
db.init_app(app)

# Crée les dossiers d’upload si besoin
for _p in (UPLOAD_ROOT, UPLOAD_FOLDER, ATTACHMENTS_FOLDER):
    try:
        _p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        app.logger.warning("Impossible de créer le dossier %s : %s", _p, e)

# -------------------------------------------------------------------
# Models
# -------------------------------------------------------------------
from models import (
    User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot,
    MessageThread, Message, FileAttachment,
    TherapySession, SessionNote,
    PatientProfile, MedicalHistory,
    Exercise, ExerciseAssignment,
    Invoice, Payment,
    SupportTicket, Guide,
    ConsentLog,
    PersonalJournalEntry, TherapyNotebookEntry,
    Specialty, City,
    ProfessionalReview,
)
# ---- Helper idempotent pour créer / récupérer le dossier patient ----------
# (Placée ici pour être définie avant toute route qui l'appelle)
if "_ensure_patient_case" not in globals():
    def _ensure_patient_case(pro_id: int, patient_user_id: int):
        """
        Garantit l'existence d'un PatientCase (si le modèle existe)
        et d'un PatientProfile pour ce patient. Renvoie (case_obj, profile).
        Ne lève pas d'exception en cas d'absence de modèles optionnels : renvoie (None, profile).
        """
        case_obj, profile = None, None

        # Profil patient (toujours utile)
        try:
            profile = PatientProfile.query.filter_by(user_id=patient_user_id).first() if "PatientProfile" in globals() else None
            if not profile and "PatientProfile" in globals():
                u = User.query.get(patient_user_id)
                profile = PatientProfile(
                    user_id=patient_user_id,
                    full_name=getattr(u, "full_name", None) or getattr(u, "username", None),
                    phone=getattr(u, "phone", None),
                    address=getattr(u, "address", None),
                    email=getattr(u, "email", None),
                )
                db.session.add(profile)
                db.session.flush()
        except Exception:
            db.session.rollback()

        # Dossier (PatientCase) si le modèle existe dans ton projet
        try:
            if "PatientCase" in globals():
                case_obj = PatientCase.query.filter_by(
                    professional_id=pro_id, patient_user_id=patient_user_id
                ).first()
                if not case_obj:
                    case_obj = PatientCase(
                        professional_id=pro_id, patient_user_id=patient_user_id, is_anonymous=False
                    )
                    db.session.add(case_obj)
            # Commit global
            db.session.commit()
        except Exception:
            db.session.rollback()

        return case_obj, profile

# -------------------------------------------------------------------
# Helpers: exercises / assignments  (fix: due_date + patient_user_id)
# -------------------------------------------------------------------

def _normalize_due_date(value):
    """Accepte '', None, str 'YYYY-MM-DD', datetime/date → retourne date ou None."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _resolve_patient_ids(patient_param):
    """
    Retourne (patient_id, patient_user_id) à partir de l'identifiant présent dans l'URL.

    - Si PatientProfile existe et qu'il est lié à User via user_id :
        patient_id = profile.id
        patient_user_id = user.id
    - Sinon, fallback : on met les deux au même ID (int(patient_param) ou user.id).
    """
    user = None
    profile = None

    # Essayer d'interpréter l'URL param comme un user_id
    try:
        uid = int(patient_param)
        user = User.query.get(uid)
    except Exception:
        user = None

    # Si PatientProfile existe, tenter de le retrouver
    if user and 'PatientProfile' in globals():
        try:
            profile = PatientProfile.query.filter_by(user_id=user.id).first()
        except Exception:
            profile = None

    if profile:
        patient_id = profile.id
        patient_user_id = user.id
    else:
        base_id = user.id if user else int(patient_param)
        patient_id = base_id
        patient_user_id = base_id

    return patient_id, patient_user_id


def _assign_exercise_to_patient(exercise, professional_id, patient_id, patient_user_id, due_date=None):
    """
    Crée/MàJ ExerciseAssignment en remplissant patient_id ET patient_user_id (NOT NULL).
    Gère due_date vide → NULL.
    """
    normalized_due = _normalize_due_date(due_date)

    # Rechercher un assignment existant pour éviter les doublons
    q = ExerciseAssignment.query.filter_by(
        exercise_id=getattr(exercise, "id", None),
        patient_id=patient_id,
        professional_id=professional_id,
    )
    if hasattr(ExerciseAssignment, "patient_user_id"):
        q = q.filter(ExerciseAssignment.patient_user_id == patient_user_id)

    assignment = q.first()

    if assignment:
        if hasattr(assignment, "due_date"):
            assignment.due_date = normalized_due
        if hasattr(assignment, "status") and not assignment.status:
            assignment.status = "active"
        if hasattr(assignment, "updated_at"):
            assignment.updated_at = datetime.utcnow()
    else:
        params = dict(
            exercise_id=getattr(exercise, "id", None),
            patient_id=patient_id,
            professional_id=professional_id,
            status="active",
        )
        if hasattr(ExerciseAssignment, "patient_user_id"):
            params["patient_user_id"] = patient_user_id
        if normalized_due is not None:
            params["due_date"] = normalized_due
        if hasattr(ExerciseAssignment, "created_at"):
            params["created_at"] = datetime.utcnow()

        assignment = ExerciseAssignment(**params)
        if hasattr(assignment, "updated_at"):
            assignment.updated_at = datetime.utcnow()
        db.session.add(assignment)

    db.session.commit()
    return assignment



# -------------------------------------------------------------------
# Admin blueprint
# -------------------------------------------------------------------
from admin_server import admin_bp, ProfessionalOrder, _build_notif
app.register_blueprint(admin_bp, url_prefix="/admin")

# -------------------------------------------------------------------
# Login manager
# -------------------------------------------------------------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def _load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

# -------------------------------------------------------------------
# I18N / Lang
# -------------------------------------------------------------------
DEFAULT_LANG = "fr"
SUPPORTED_LANGS = {"fr", "en", "ar"}
LEGACY_LANG_COOKIE = "lang"
LANG_COOKIE = "tighri_lang"
LANG_MAX_AGE = 60 * 60 * 24 * 180

def _normalize_lang(code: str | None):
    if not code:
        return DEFAULT_LANG
    v = str(code).strip().lower()
    if "-" in v:
        v = v.split("-", 1)[0]
    return v if v in SUPPORTED_LANGS else DEFAULT_LANG

def _cookie_domain_for(host: str | None):
    if not host:
        return None
    host = host.split(":")[0]
    if host in ("localhost",) or host.replace(".", "").isdigit():
        return None
    parts = host.split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return None

@app.before_request
def _load_locale():
    param = request.args.get("lang")
    cookie_new = request.cookies.get(LANG_COOKIE)
    cookie_old = request.cookies.get(LEGACY_LANG_COOKIE)
    accept = request.accept_languages.best_match(SUPPORTED_LANGS) if request.accept_languages else None
    lang = param or cookie_new or cookie_old or accept
    g.current_locale = _normalize_lang(lang)

@app.after_request
def _vary_on_cookie_for_lang(resp):
    ct = resp.headers.get("Content-Type", "")
    if "text/html" in ct:
        existing_vary = resp.headers.get("Vary")
        resp.headers["Vary"] = "Cookie" if not existing_vary else f"{existing_vary}, Cookie"
        resp.headers["Cache-Control"] = "private, no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp

# t() helper pour templates
@app.context_processor
def inject_t_helper():
    def t(key: str, default: str | None = None, **kwargs):
        lang = getattr(g, "current_locale", DEFAULT_LANG)
        data = current_app.config.get("I18N", {}) or {}
        node = data.get(lang) or {}
        for part in key.replace(":", ".").split("."):
            if isinstance(node, dict):
                node = node.get(part)
            else:
                node = None
                break
        text = node if isinstance(node, str) else (default or key.split(".")[-1].replace("_", " "))
        try:
            return text.format(**kwargs) if kwargs else text
        except Exception:
            return text
    return dict(t=t)

@app.route("/set-language/clear")
def clear_language_cookie():
    resp = make_response(redirect(request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.delete_cookie(LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

@app.route("/set-language/<lang_code>", endpoint="set_language")
def set_language(lang_code):
    code = _normalize_lang(lang_code)
    resp = make_response(redirect(request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.set_cookie(LANG_COOKIE, code, max_age=LANG_MAX_AGE, httponly=False, secure=True, samesite="Lax", domain=dom, path="/")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

@app.route("/set-language")
def set_language_qs():
    code = _normalize_lang(request.args.get("lang"))
    resp = make_response(redirect(request.args.get("next") or request.referrer or url_for("index")))
    dom = _cookie_domain_for(request.host)
    resp.set_cookie(LANG_COOKIE, code, max_age=LANG_MAX_AGE, httponly=False, secure=True, samesite="Lax", domain=dom, path="/")
    resp.delete_cookie(LEGACY_LANG_COOKIE, domain=dom, path="/", samesite="Lax")
    return resp

@app.route("/set_language")
def set_language_fallback():
    lang_code = request.args.get("lang")
    nxt = request.args.get("next") or request.referrer or url_for("index")
    if not lang_code:
        return redirect(nxt)
    return redirect(url_for("set_language_qs", lang=lang_code, next=nxt))

# -------------------------------------------------------------------
# Canonical host
# -------------------------------------------------------------------
PRIMARY_HOST = os.getenv("PRIMARY_HOST", "www.tighri.ma")

@app.before_request
def _enforce_primary_domain():
    host = request.host.split(":")[0]
    if host in ("localhost", "127.0.0.1"):
        return
    if host != PRIMARY_HOST:
        return redirect(request.url.replace(host, PRIMARY_HOST, 1), code=301)

# -------------------------------------------------------------------
# Emails (safe wrapper)
# -------------------------------------------------------------------
from notifications import send_email as _notif_send_email
def safe_send_email(to_addr: str, subject: str, body_text: str, html: str | None = None) -> bool:
    try:
        if not to_addr:
            current_app.logger.warning("[EMAIL] destinataire manquant")
            return False
        ok = _notif_send_email(to_addr, subject, body_text, html)
        (current_app.logger.info if ok else current_app.logger.error)(
            "[EMAIL] %s -> %s : %s", "envoyé" if ok else "échec", to_addr, subject
        )
        return ok
    except Exception as e:
        current_app.logger.exception("safe_send_email exception: %s", e)
        return False

# -------------------------------------------------------------------
# PIL (images)
# -------------------------------------------------------------------
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
PLACEHOLDER_AVATAR = os.path.join(app.root_path, "static", "avatar_default.webp")
PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _doc_ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_DOC_EXT

def _process_and_save_profile_image(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _ext_ok(filename):
        raise ValueError("Extension non autorisée")
    raw = file_storage.read()
    if not _PIL_OK:
        raise RuntimeError("Le traitement d'image nécessite Pillow (PIL).")
    try:
        img = Image.open(io.BytesIO(raw)); img.verify()
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")
    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))
    img_square = ImageOps.fit(img_no_exif, (512, 512), Image.Resampling.LANCZOS)
    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = UPLOAD_FOLDER / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_name

def _save_attachment(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _doc_ext_ok(filename):
        raise ValueError("Extension non autorisée")
    content = file_storage.read()
    name = f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    out_path = ATTACHMENTS_FOLDER / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(content)
    return name

def _avatar_file_for(pid: int) -> Optional[str]:
    if not os.path.isdir(AVATAR_DIR):
        return None
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        path = os.path.join(AVATAR_DIR, f"{pid}{ext}")
        if os.path.isfile(path):
            return path
    return None

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

# -------------------------------------------------------------------
# Fichiers (Render Disk)
# -------------------------------------------------------------------
@app.route("/u/profiles/<path:filename>", endpoint="u_profiles")
def u_profiles(filename: str):
    if not filename or ".." in filename or filename.startswith("/"):
        abort(404)
    fpath = UPLOAD_FOLDER / os.path.basename(filename)
    if not fpath.exists():
        return _avatar_fallback_response()
    resp = send_from_directory(str(UPLOAD_FOLDER), os.path.basename(filename), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000"
    return resp

@app.route("/u/attachments/<path:filename>", endpoint="u_attachments")
def u_attachments(filename: str):
    if not filename or ".." in filename or filename.startswith("/"):
        abort(404)
    fpath = ATTACHMENTS_FOLDER / os.path.basename(filename)
    if not fpath.exists():
        abort(404)
    resp = send_from_directory(str(ATTACHMENTS_FOLDER), os.path.basename(filename), conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000"
    return resp

def _normalize_disk_url(value: str | None) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if v.startswith("http://") or v.startswith("https://"):
        if v.startswith("http://"):
            v = "https://" + v[len("http://"):]
        return v
    if v.startswith("/media/profiles/"):
        v = v.split("/media/profiles/", 1)[-1]
        return url_for("u_profiles", filename=os.path.basename(v))
    if v.startswith("/u/profiles/"):
        return v
    if v.startswith("/u/attachments/"):
        return v
    return url_for("u_profiles", filename=os.path.basename(v))

def _pro_photo_field(pro: Professional, index: int) -> Optional[str]:
    candidates_by_index = {
        1: ("image_url", "photo_main", "avatar_url"),
        2: ("image_url2", "photo_alt1", "gallery1", "gallery_1", "photo2", "photo_secondaire1"),
        3: ("image_url3", "photo_alt2", "gallery2", "gallery_2", "photo3", "photo_secondaire2"),
    }
    for field in candidates_by_index.get(index, ()):
        if hasattr(pro, field):
            val = getattr(pro, field)
            if val:
                return str(val)
    return None

def professional_photo_url(pro: Professional, index: int) -> Optional[str]:
    raw = _pro_photo_field(pro, index)
    if raw:
        return _normalize_disk_url(raw)
    if index == 1 and not raw:
        return url_for("profile_photo", professional_id=pro.id)
    return None

def professional_gallery_urls(pro: Professional) -> list[str]:
    urls = []
    for i in (1, 2, 3):
        u = professional_photo_url(pro, i)
        if u:
            urls.append(u)
    return urls

@app.context_processor
def inject_gallery_helpers():
    return {
        "professional_photo_url": professional_photo_url,
        "professional_gallery_urls": professional_gallery_urls,
    }

# -------------------------------------------------------------------
# Listes (ORM + seeds)
# -------------------------------------------------------------------
try:
    from seeds_taxonomy import (
        SPECIALTY_FAMILIES,
        CITY_OBJECTS,
        ALL_CITIES as SEED_CITIES,
        ALL_SPECIALTIES as SEED_SPECIALTIES,
    )
except Exception:
    SPECIALTY_FAMILIES = []
    CITY_OBJECTS = []
    SEED_CITIES = ["Casablanca", "Rabat", "Marrakech", "Fès", "Tanger", "Agadir"]
    SEED_SPECIALTIES = [
        "Psychologue", "Psychiatre", "Psychothérapeute", "Coach",
        "Orthophoniste", "Psychomotricien", "Kinésithérapeute"
    ]

def _ui_cities():
    try:
        return [{"id": c.id, "name": c.name} for c in City.query.order_by(City.name.asc()).all()]
    except Exception:
        return []

def _ui_specialties():
    try:
        return [{"id": s.id, "name": s.name, "category": s.category} for s in Specialty.query.order_by(Specialty.name.asc()).all()]
    except Exception:
        return []

def _ui_families_rows():
    try:
        rows = (
            db.session.query(Specialty.category)
            .filter(Specialty.category.isnot(None), Specialty.category != "")
            .distinct()
            .order_by(Specialty.category.asc())
            .all()
        )
        out = []
        for i, r in enumerate(rows, start=1):
            out.append({"id": i, "name": r[0]})
        return out
    except Exception:
        return []

@app.context_processor
def inject_taxonomies_for_forms():
    return {
        "ALL_CITIES": SEED_CITIES,
        "ALL_SPECIALTIES": SEED_SPECIALTIES,
    }

# -------------------------------------------------------------------
# Routes techniques
# -------------------------------------------------------------------
@app.route("/robots.txt")
def robots():
    txt_path = Path(app.static_folder or (BASE_DIR / "static")) / "robots.txt"
    if txt_path.exists():
        return send_from_directory(app.static_folder, "robots.txt", mimetype="text/plain")
    return ("User-agent: *\nDisallow:\n", 200, {"Content-Type": "text/plain"})

def render_or_text(template_name: str, fallback_title: str, **kwargs):
    try:
        return render_template(template_name, **kwargs)
    except TemplateNotFound:
        body = f"<h1 style='font-family:system-ui,Segoe UI,Arial'>Tighri — {fallback_title}</h1>"
        body += "<p>Template manquant : <code>{}</code>. Cette page fonctionne en mode fallback sans casser l'app.</p>".format(template_name)
        return body, 200, {"Content-Type": "text/html; charset=utf-8"}

@app.get("/favicon.ico", endpoint="favicon_ico")
def favicon_ico():
    static_dir = os.path.join(app.root_path, "static")
    return send_from_directory(static_dir, "favicon.ico", mimetype="image/x-icon")

@app.get("/favicon.png", endpoint="favicon_png")
def favicon_png():
    static_dir = os.path.join(app.root_path, "static")
    return send_from_directory(static_dir, "favicon.png", mimetype="image/png")

# -------------------------------------------------------------------
# Pages publiques (index / listings)
# -------------------------------------------------------------------
@app.route("/", endpoint="index")
def index():
    try:
        base = (
            db.session.query(Professional)
            .outerjoin(ProfessionalOrder, ProfessionalOrder.professional_id == Professional.id)
            .filter(Professional.status == 'valide')
            .order_by(
                db.func.coalesce(ProfessionalOrder.order_priority, 999999).asc(),
                Professional.is_featured.desc(),
                db.func.coalesce(Professional.featured_rank, 999999).asc(),
                Professional.created_at.desc(),
                Professional.id.desc()
            )
        )
        top_professionals = base.limit(9).all()
        top_ids = [p.id for p in top_professionals]
        more_professionals = base.filter(~Professional.id.in_(top_ids)).all() if top_ids else base.offset(9).all()
    except Exception as e:
        app.logger.warning("Classement admin indisponible (%s), fallback 'featured puis récents'.", e)
        fb = (
            Professional.query
            .filter_by(status='valide')
            .order_by(
                Professional.is_featured.desc(),
                db.func.coalesce(Professional.featured_rank, 999999).asc(),
                Professional.created_at.desc(),
                Professional.id.desc()
            )
        )
        top_professionals = fb.limit(9).all()
        top_ids = [p.id for p in top_professionals]
        more_professionals = fb.filter(~Professional.id.in_(top_ids)).all() if top_ids else fb.offset(9).all()

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_template("index.html",
        top_professionals=top_professionals,
        more_professionals=more_professionals,
        cities=cities, families=families, specialties=specialties
    )

@app.route("/anthecc", endpoint="anthecc")
def anthecc():
    tpl = BASE_DIR / "templates" / "anthecc.html"
    return render_template("anthecc.html") if tpl.exists() else ("ANTHECC", 200)

@app.route("/about", endpoint="about")
def about():
    return render_template("about.html")

@app.route("/contact", endpoint="contact")
def contact():
    return render_template("contact.html")

@app.route("/professionals", endpoint="professionals")
def professionals():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    city_id = request.args.get("city_id", type=int)
    family = (request.args.get("family") or "").strip()
    specialty = (request.args.get("specialty") or "").strip()
    specialty_id = request.args.get("specialty_id", type=int)
    mode = (request.args.get("mode") or "").strip().lower()
    if mode == "visio":
        mode = "en_ligne"

    qry = Professional.query.filter_by(status='valide')

    if q:
        like = f"%{q}%"
        conds = []
        for attr in ("name", "full_name", "description", "specialty", "location", "address"):
            if hasattr(Professional, attr):
                conds.append(getattr(Professional, attr).ilike(like))
        if conds:
            qry = qry.filter(or_(*conds))

    if city_id is not None and hasattr(Professional, "city_id"):
        qry = qry.filter(Professional.city_id == city_id)
    elif city and hasattr(Professional, "location"):
        qry = qry.filter(Professional.location.ilike(f"%{city}%"))

    if specialty_id is not None and hasattr(Professional, "primary_specialty_id"):
        qry = qry.filter(Professional.primary_specialty_id == specialty_id)
    elif specialty and hasattr(Professional, "specialty"):
        qry = qry.filter(Professional.specialty.ilike(f"%{specialty}%"))

    if family:
        like_family = family
        qry = qry.filter(
            or_(
                Professional.primary_specialty.has(Specialty.category.ilike(like_family)),
                Professional.specialties.any(Specialty.category.ilike(like_family)),
                Professional.specialty.ilike(f"%{family}%"),
            )
        )

    if mode and hasattr(Professional, "consultation_types"):
        qry = qry.filter(Professional.consultation_types.ilike(f"%{mode}%"))

    pros = qry.order_by(Professional.is_featured.desc(), Professional.created_at.desc()).all()

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_template("professionals.html",
                           professionals=pros,
                           specialty=specialty, search_query=q,
                           cities=cities, families=families, specialties=specialties)

@app.route("/professional/<int:professional_id>", endpoint="professional_detail")
def professional_detail(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    return render_template("professional_detail.html", professional=professional)

# -------------------------------------------------------------------
# Médias / Photos
# -------------------------------------------------------------------
@app.route("/media/profile/<int:professional_id>", endpoint="profile_photo")
def profile_photo(professional_id: int):
    pro = Professional.query.get_or_404(professional_id)
    raw_url = (pro.image_url or "").strip()

    if raw_url.startswith("/media/profiles/"):
        fname = raw_url.split("/media/profiles/")[-1]
        safe_name = os.path.basename(fname)
        fpath = UPLOAD_FOLDER / safe_name
        if fpath.exists():
            resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
            resp.headers["Cache-Control"] = "public, max-age=31536000"
            return resp
        return _avatar_fallback_response()

    if not raw_url:
        file_path = _avatar_file_for(professional_id)
        if file_path and os.path.isfile(file_path):
            return send_from_directory(AVATAR_DIR, os.path.basename(file_path), max_age=60*60*24*7)
        if os.path.isfile(PLACEHOLDER_AVATAR):
            return send_from_directory(os.path.join(app.root_path, "static"), "avatar_default.webp", max_age=86400)
        return _avatar_fallback_response()

    if raw_url.startswith("http://"):
        raw_url = "https://" + raw_url[len("http://"):]
    parsed = urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        return _avatar_fallback_response()

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; TighriBot/1.0; +https://www.tighri.com)",
        "Referer": "https://www.tighri.com",
    }
    try:
        r = requests.get(raw_url, headers=headers, timeout=8, stream=True)
        r.raise_for_status()
    except Exception:
        return _avatar_fallback_response()

    content_type = r.headers.get("Content-Type", "image/jpeg")
    resp = Response(r.content, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

@app.route("/media/profile/<int:professional_id>/<int:index>", endpoint="profile_photo_n")
def profile_photo_n(professional_id: int, index: int):
    if index not in (1, 2, 3):
        abort(404)
    pro = Professional.query.get_or_404(professional_id)
    raw = _pro_photo_field(pro, index)
    if index == 1 and not raw:
        return redirect(url_for("profile_photo", professional_id=professional_id))

    url = _normalize_disk_url(raw) if raw else None

    if url and (url.startswith("http://") or url.startswith("https://")):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        try:
            r = requests.get(url, timeout=8, stream=True)
            r.raise_for_status()
        except Exception:
            return _avatar_fallback_response()
        resp = Response(r.content, mimetype=r.headers.get("Content-Type", "image/jpeg"))
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    if url:
        fname = url.split("/u/profiles/")[-1]
        fpath = UPLOAD_FOLDER / os.path.basename(fname)
        if fpath.exists():
            resp = send_from_directory(str(UPLOAD_FOLDER), os.path.basename(fname), conditional=True)
            resp.headers["Cache-Control"] = "public, max-age=31536000"
            return resp

    return _avatar_fallback_response()

@app.route("/avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id: int):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# Uploads pro
@app.route("/professional/profile/photo", methods=["GET", "POST"], endpoint="professional_upload_photo")
@login_required
def professional_upload_photo():
    if current_user.user_type != "professional":
        flash("Accès non autorisé")
        return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("professional_dashboard"))

    if request.method == "POST":
        file = request.files.get("photo")
        if not file:
            flash("Veuillez sélectionner une image.", "warning")
            return redirect(url_for("professional_upload_photo"))
        try:
            saved_name = _process_and_save_profile_image(file)
            pro.image_url = f"/u/profiles/{saved_name}"
            db.session.commit()
            flash("Photo de profil mise à jour avec succès.", "success")
            return redirect(url_for("professional_dashboard"))

        except RuntimeError:
            current_app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            current_app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")

    return render_or_text("upload_photo.html", "Upload photo", professional=pro)

@app.route("/professional/profile/photo/<int:index>", methods=["GET", "POST"], endpoint="professional_upload_photo_n")
@login_required
def professional_upload_photo_n(index: int):
    if current_user.user_type != "professional" or index not in (1, 2, 3):
        flash("Accès non autorisé")
        return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("professional_dashboard"))

    if request.method == "POST":
        file = request.files.get("photo")
        if not file:
            flash("Veuillez sélectionner une image.", "warning")
            return redirect(url_for("professional_upload_photo_n", index=index))
        try:
            saved_name = _process_and_save_profile_image(file)
            field = "image_url" if index == 1 else ("image_url2" if index == 2 else "image_url3")
            setattr(pro, field, f"/u/profiles/{saved_name}")
            db.session.commit()
            flash(f"Photo #{index} mise à jour avec succès.", "success")
            return redirect(url_for("professional_dashboard"))
        except RuntimeError:
            current_app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            current_app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")

    return render_or_text("upload_photo.html", "Upload photo", professional=pro, index=index)

@app.route("/professional/profile/photos-upload", methods=["POST"], endpoint="professional_photos_upload")
@login_required
def professional_photos_upload_alias():
    return professional_upload_photo()

# -------------------------------------------------------------------
# Auth local
# -------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"], endpoint="register")
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        phone = (request.form.get("phone") or "").strip()

        if not username or not email or not password or not phone:
            flash("Tous les champs (dont téléphone) sont obligatoires.")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré")
            return redirect(url_for("register"))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type="patient",
            phone=phone,
        )
        db.session.add(user)
        db.session.commit()
        # Crée un profil patient vide pour l'espace patient
        try:
            if not PatientProfile.query.filter_by(user_id=user.id).first():
                db.session.add(PatientProfile(user_id=user.id))
                db.session.commit()
        except Exception:
            db.session.rollback()
        flash("Compte patient créé avec succès!")
        return redirect(url_for("login"))

    return render_or_text("register.html", "Inscription")

@app.route("/professional_register", methods=["GET", "POST"], endpoint="professional_register")
def professional_register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password", "")
        specialty = (request.form.get("specialty") or "").strip()
        city = (request.form.get("city") or "").strip()
        description = (request.form.get("description") or "").strip()
        experience_raw = request.form.get("experience", "0")
        fee_raw = request.form.get("consultation_fee", "0")
        phone = (request.form.get("phone") or "").strip()

        city_id = request.form.get("city_id", type=int)
        primary_specialty_id = request.form.get("primary_specialty_id", type=int) or request.form.get("specialty_id", type=int)

        facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        instagram_url = (request.form.get('instagram_url') or '').strip() or None
        tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        youtube_url   = (request.form.get('youtube_url')   or '').strip() or None

        if not username or not email or not password or not phone:
            flash("Tous les champs obligatoires (dont téléphone) ne sont pas remplis.")
            return redirect(url_for("professional_register"))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for("professional_register"))
        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré")
            return redirect(url_for("professional_register"))

        try:
            experience = int((experience_raw or "0").strip())
        except ValueError:
            experience = 0
        try:
            consultation_fee = float((fee_raw or "0").replace(",", "."))
        except ValueError:
            consultation_fee = 0.0

        try:
            user = User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                user_type="professional",
                phone=phone,
            )
            db.session.add(user)

            professional = Professional(
                name=username,
                description=description or "Profil en cours de complétion.",
                specialty=specialty or "Psychologue",
                location=city or "Casablanca",
                experience_years=experience,
                consultation_fee=consultation_fee,
                phone=phone or None,
                availability='disponible',
                consultation_types='cabinet',
                facebook_url=facebook_url,
                instagram_url=instagram_url,
                tiktok_url=tiktok_url,
                youtube_url=youtube_url,
                social_links_approved=False,
                status='en_attente',
            )
            if city_id is not None and hasattr(professional, "city_id"):
                professional.city_id = city_id
            if primary_specialty_id is not None and hasattr(professional, "primary_specialty_id"):
                professional.primary_specialty_id = primary_specialty_id

            spec_ids = [int(x) for x in request.form.getlist("specialty_ids") if str(x).isdigit()]

            new_name = (request.form.get("new_specialty_name") or "").strip()
            new_family = (request.form.get("new_specialty_family") or "").strip()
            if new_name:
                existing = Specialty.query.filter(db.func.lower(Specialty.name) == new_name.lower()).first()
                if not existing:
                    existing = Specialty(name=new_name, category=(new_family or None))
                    db.session.add(existing)
                    db.session.flush()
                spec_ids.append(existing.id)

            primary_spec_id = request.form.get("primary_specialty_id", type=int)
            if primary_spec_id:
                professional.primary_specialty_id = primary_spec_id
            elif not getattr(professional, "primary_specialty_id", None) and spec_ids:
                professional.primary_specialty_id = spec_ids[0]

            if spec_ids:
                professional.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all()

            if professional.primary_specialty_id and not (professional.specialty or "").strip():
                ps = db.session.get(Specialty, professional.primary_specialty_id)
                if ps:
                    professional.specialty = ps.name

            db.session.add(professional)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la création du compte professionnel. Réessayez.", "danger")
            return redirect(url_for("professional_register"))

        flash("Compte professionnel créé avec succès! Un administrateur validera votre profil.")
        return redirect(url_for("login"))

    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()
    return render_or_text("professional_register.html", "Inscription pro",
                           cities=cities, families=families, specialties=specialties)

# --------- Login unique (GET+POST) ---------
@app.route("/login", methods=["GET", "POST"], endpoint="login")
def login():
    if request.method == "POST":
        username_or_email = (request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            or_(User.username == username_or_email, User.email == username_or_email.lower())
        ).first()

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user, remember=remember, duration=timedelta(days=60))
            flash("Connexion réussie!")
            if user.user_type == "professional":
                return redirect(url_for("professional_dashboard"))
            else:
                # crée profil patient si pas présent
                try:
                    if not PatientProfile.query.filter_by(user_id=user.id).first():
                        db.session.add(PatientProfile(user_id=user.id))
                        db.session.commit()
                except Exception:
                    db.session.rollback()
                return redirect(url_for("patient_home"))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")
    return render_or_text("login.html", "Connexion")

# --------- Logout unique ---------
@app.get("/logout")  # endpoint implicite = 'logout'
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

# -------------------------------------------------------------------
# OAuth Google
# -------------------------------------------------------------------
from authlib.integrations.flask_client import OAuth
oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    access_token_url="https://oauth2.googleapis.com/token",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    api_base_url="https://www.googleapis.com/oauth2/v3/",
    client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
)

@app.route("/auth/google")
def auth_google():
    redirect_uri = os.environ.get("OAUTH_REDIRECT_URI", url_for("auth_google_callback", _external=True, _scheme="https"))
    return google.authorize_redirect(redirect_uri)

@app.route("/auth/google/callback")
def auth_google_callback():
    try:
        token = google.authorize_access_token()
        userinfo = google.get("userinfo").json()
        sub = userinfo.get("sub")
        email = (userinfo.get("email") or "").lower().strip()
        name = userinfo.get("name")
        picture = userinfo.get("picture")

        if not email:
            flash("Impossible de récupérer votre email Google.", "danger")
            return redirect(url_for("login"))

        user = User.query.filter(or_(User.oauth_sub == sub, User.email == email)).first()

        if user:
            changed = False
            if not user.oauth_sub and sub:
                user.oauth_provider = "google"; user.oauth_sub = sub; changed = True
            if picture and not user.picture_url:
                user.picture_url = picture; changed = True
            if name and not user.full_name:
                user.full_name = name; changed = True
            if changed:
                db.session.commit()
        else:
            username_base = email.split("@")[0]
            username = username_base
            i = 1
            while User.query.filter_by(username=username).first():
                username = f"{username_base}{i}"; i += 1

            user = User(
                username=username, email=email,
                oauth_provider="google", oauth_sub=sub,
                full_name=name, picture_url=picture,
                user_type="professional"
            )
            db.session.add(user); db.session.commit()

        login_user(user, remember=True, duration=timedelta(days=60))
        flash("Connexion via Google réussie ✅", "success")
        return redirect(url_for("professional_dashboard" if user.user_type == "professional" else "patient_home"))

    except Exception:
        flash("Connexion Google impossible. Réessayez.", "danger")
        return redirect(url_for("login"))

# =========================
#   RESET PASSWORD
# =========================
def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()

def issue_reset_token(user, hours=24) -> str:
    tok = secrets.token_urlsafe(32)
    user.reset_token_hash = _hash_token(tok)
    user.reset_token_expires_at = datetime.utcnow() + timedelta(hours=hours)
    db.session.commit()
    return tok

def consume_token_to_user(token: str):
    if not token:
        return None
    h = _hash_token(token)
    u = User.query.filter_by(reset_token_hash=h).first()
    if not u or not u.reset_token_expires_at or u.reset_token_expires_at < datetime.utcnow():
        return None
    return u

@app.route("/change_password", methods=["GET","POST"], endpoint="change_password")
@login_required
def change_password():
    if request.method == "POST":
        old = (request.form.get("old") or "").strip()
        new = (request.form.get("new") or "").strip()
        confirm = (request.form.get("confirm") or "").strip()

        has_local_pw = bool(current_user.password_hash)
        if has_local_pw:
            if not check_password_hash(current_user.password_hash, old):
                flash("Ancien mot de passe incorrect.", "danger")
                return redirect(url_for("change_password"))
            if old and new and old == new:
                flash("Le nouveau mot de passe doit être différent de l'ancien.", "danger")
                return redirect(url_for("change_password"))
        else:
            if old:
                flash("Ce compte n'a pas de mot de passe local.", "warning")
                return redirect(url_for("change_password"))

        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for("change_password"))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for("change_password"))

        current_user.password_hash = generate_password_hash(new)
        db.session.commit()
        flash("Mot de passe modifié.", "success")
        return redirect(url_for("index"))
    return render_or_text("change_password.html", "Changer le mot de passe")

@app.route("/forgot_password", methods=["GET","POST"], endpoint="forgot_password")
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        flash("Si le compte existe, un email de réinitialisation a été envoyé.", "info")
        if not email:
            return redirect(url_for("login"))

        user = User.query.filter_by(email=email).first()
        if not user:
            return redirect(url_for("login"))

        try:
            raw_token = issue_reset_token(user, hours=24)
            reset_link = url_for("reset_password", token=raw_token, _external=True, _scheme="https")
            subj = f"{BRAND_NAME} — Réinitialisation du mot de passe"
            txt = (
                f"Bonjour,\n\nVous avez demandé à réinitialiser votre mot de passe {BRAND_NAME}.\n"
                f"Cliquez sur ce lien (valable 24h) : {reset_link}\n\n"
                f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
            )
            html = (
                f"<p>Bonjour,</p><p>Vous avez demandé à réinitialiser votre mot de passe "
                f"<strong>{BRAND_NAME}</strong>.</p>"
                f"<p><a href='{reset_link}'>Réinitialiser mon mot de passe</a> (valable 24&nbsp;heures)</p>"
                f"<p>Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail.</p>"
            )
            safe_send_email(user.email, subj, txt, html)
        except Exception as e:
            current_app.logger.warning("forgot_password: %s", e)
        return redirect(url_for("login"))
    return render_or_text("forgot_password.html", "Mot de passe oublié")

@app.route("/reset_password/<token>", methods=["GET","POST"], endpoint="reset_password")
def reset_password(token: str):
    user = consume_token_to_user(token)
    if not user:
        flash("Lien invalide ou expiré. Refaite une demande.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new = (request.form.get("new") or "").strip()
        confirm = (request.form.get("confirm") or "").strip()
        if len(new) < 8:
            flash("Le nouveau mot de passe doit contenir au moins 8 caractères.", "danger")
            return redirect(url_for("reset_password", token=token))
        if new != confirm:
            flash("La confirmation ne correspond pas.", "danger")
            return redirect(url_for("reset_password", token=token))

        user.password_hash = generate_password_hash(new)
        user.reset_token_hash = None
        user.reset_token_expires_at = None
        db.session.commit()
        flash("Mot de passe réinitialisé. Vous pouvez vous connecter.", "success")
        return redirect(url_for("login"))
    return render_or_text("reset_password.html", "Réinitialiser le mot de passe")

# =========================
#  HELPER PRO (unique, sans doublon)
# =========================
def _current_professional_or_403():
    if not getattr(current_user, "is_authenticated", False) or getattr(current_user, "user_type", None) != "professional":
        abort(403)
    pro = (
        Professional.query
        .filter(
            (Professional.name == (getattr(current_user, "full_name", "") or "")) |
            (Professional.name == (getattr(current_user, "username", "") or ""))
        )
        .first()
    ) or Professional.query.filter_by(name=getattr(current_user, "username", None)).first()
    if not pro:
        abort(403)
    return pro

# =========================
#   MESSAGERIE — PRO (INBOX)  ✅ unique, après app = Flask(...)
# =========================
@app.route("/pro/messages", methods=["GET"], endpoint="pro_messages")
@login_required
def pro_messages():
    if getattr(current_user, "user_type", None) != "professional":
        abort(403)
    pro = _current_professional_or_403()

    q = (request.args.get("q") or "").strip()
    base = MessageThread.query.filter_by(professional_id=pro.id)

    if q:
        like = f"%{q}%"
        # compat patient_id / patient_user_id
        pid_col = MessageThread.patient_id if hasattr(MessageThread, "patient_id") else MessageThread.patient_user_id
        base = (
            base.join(User, User.id == pid_col)
                .filter(or_(User.username.ilike(like),
                            User.full_name.ilike(like),
                            User.email.ilike(like),
                            User.phone.ilike(like)))
        )

    threads = (base.order_by(MessageThread.updated_at.desc().nullslast(),
                             MessageThread.id.desc()).all())

    items = []
    for th in threads:
        pid = getattr(th, "patient_id", None) or getattr(th, "patient_user_id", None)
        patient = User.query.get(pid) if pid else None

        last_msg = (Message.query.filter_by(thread_id=getattr(th, "id", None))
                              .order_by(Message.created_at.desc(), Message.id.desc())
                              .first())

        last_at = getattr(last_msg, "created_at", None)
        last_text = (
            getattr(last_msg, "body", None)
            or ("📎 Pièce jointe" if getattr(last_msg, "attachment_id", None) else None)
            or ("🔊 Message audio" if getattr(last_msg, "audio_url", None) else None)
            or ""
        )
        sender_id = getattr(last_msg, "sender_user_id", None) or getattr(last_msg, "sender_id", None)
        unread = bool(last_msg and sender_id and sender_id != getattr(current_user, "id", None))

        items.append({
            "thread": th,
            "patient": patient,
            "last_at": last_at,
            "last_text": last_text,
            "unread": unread,
        })

    unread_count = sum(1 for it in items if it["unread"])

    return render_or_text("pro/messages_inbox.html", "Messagerie sécurisée",
                          items=items, q=q, unread_count=unread_count, professional=pro)



# =========================
# =========================
#   ESPACE PRO / RDV
# =========================

# Helper robuste : résout le pro courant ou 403 (disponible pour toutes les routes ci-dessous)
def _current_professional_or_403():
    from flask import abort
    from flask_login import current_user
    if not getattr(current_user, "is_authenticated", False) or getattr(current_user, "user_type", None) != "professional":
        abort(403)
    pro = (
        Professional.query
        .filter(
            (Professional.name == (getattr(current_user, "full_name", "") or "")) |
            (Professional.name == (getattr(current_user, "username", "") or ""))
        )
        .first()
    )
    if not pro:
        abort(403)
    return pro


@app.route("/professional_dashboard", endpoint="professional_dashboard")
@login_required
def professional_dashboard():
    if current_user.user_type != "professional":
        flash("Accès non autorisé")
        return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé")
        return redirect(url_for("index"))
    appointments = Appointment.query.filter_by(professional_id=professional.id)\
        .order_by(Appointment.appointment_date.desc()).all()
    return render_or_text("professional_dashboard.html",
                           "Tableau de bord pro",
                           professional=professional, appointments=appointments)


@app.route("/professional/availability", methods=["GET","POST"], endpoint="professional_availability")
@login_required
def professional_availability():
    from datetime import date, datetime
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))

    if request.method == "POST":
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        def add_window(day, s, e, flag):
            s = (s or "").strip(); e = (e or "").strip()
            if flag and s and e:
                db.session.add(ProfessionalAvailability(
                    professional_id=professional.id, day_of_week=day,
                    start_time=s, end_time=e, is_available=True
                ))

        for day in range(7):
            base_flag = request.form.get(f"available_{day}") == "on"
            add_window(day, request.form.get(f"start_time_{day}", ""), request.form.get(f"end_time_{day}", ""), base_flag)
            add_window(day, request.form.get(f"start_time_{day}_2", ""), request.form.get(f"end_time_{day}_2", ""), request.form.get(f"available_{day}_2") == "on" or base_flag)
            add_window(day, request.form.get(f"start_time_{day}_3", ""), request.form.get(f"end_time_{day}_3", ""), request.form.get(f"available_{day}_3") == "on" or base_flag)

        db.session.commit()
        flash("Disponibilités mises à jour avec succès!")
        return redirect(url_for("professional_availability"))

    all_avs = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    windows_by_day = {d: [] for d in range(7)}
    for av in all_avs:
        windows_by_day.get(av.day_of_week, []).append(av)
    availability_dict = {d: (windows_by_day[d][0] if windows_by_day[d] else None) for d in range(7)}

    return render_or_text("professional_availability.html",
                           "Disponibilités pro",
                           professional=professional,
                           availabilities=availability_dict,
                           windows_by_day=windows_by_day)


@app.route("/professional/unavailable-slots", methods=["GET","POST"], endpoint="professional_unavailable_slots")
@login_required
def professional_unavailable_slots():
    from datetime import date, datetime
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))

    if request.method == "POST":
        date_str = request.form.get("date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        reason = (request.form.get("reason") or "").strip()
        try:
            slot_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Format de date invalide"); return redirect(url_for("professional_unavailable_slots"))
        if slot_date < date.today():
            flash("Vous ne pouvez pas bloquer une date dans le passé"); return redirect(url_for("professional_unavailable_slots"))
        if not start_time or not end_time:
            flash("Heure de début et de fin obligatoires."); return redirect(url_for("professional_unavailable_slots"))

        db.session.add(UnavailableSlot(
            professional_id=professional.id,
            date=slot_date, start_time=start_time, end_time=end_time, reason=reason
        ))
        db.session.commit()
        flash("Créneau indisponible ajouté avec succès!")
        return redirect(url_for("professional_unavailable_slots"))

    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional.id)\
        .order_by(UnavailableSlot.date.desc()).all()
    return render_or_text("professional_unavailable_slots.html",
                           "Créneaux indisponibles",
                           professional=professional, unavailable_slots=unavailable_slots)


# Edition profil pro
@app.route("/professional/profile", methods=["GET", "POST"], endpoint="professional_edit_profile")
@login_required
def professional_edit_profile():
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError

    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        professional = Professional(
            name=current_user.username,
            description="Profil en cours de complétion.",
            status="en_attente",
            consultation_duration_minutes=45,
            buffer_between_appointments_minutes=15,
            availability="disponible",
        )

    if request.method == "POST":
        f = request.form

        # Champs texte "legacy safe"
        professional.name = (f.get("name", "") or professional.name).strip()
        professional.specialty = (f.get("specialty", "") or professional.specialty or "").strip() or professional.specialty
        professional.description = (f.get("description", "") or professional.description or "").strip() or professional.description
        professional.location = (f.get("location", "") or professional.location or "").strip() or professional.location
        professional.address = (f.get("address", "") or professional.address or "").strip() or professional.address
        professional.phone = (f.get("phone", "") or professional.phone or "").strip() or professional.phone

        # Clés étrangères optionnelles
        city_id = f.get("city_id", type=int)
        if city_id is not None and hasattr(professional, "city_id"):
            professional.city_id = city_id

        ps_id = f.get("primary_specialty_id", type=int) or f.get("specialty_id", type=int)
        if ps_id is not None and hasattr(professional, "primary_specialty_id"):
            professional.primary_specialty_id = ps_id

        # Liste de spécialités
        spec_ids = [int(x) for x in f.getlist("specialty_ids") if str(x).isdigit()]

        # Création "à la volée" d'une spécialité si fournie
        new_name = (f.get("new_specialty_name") or "").strip()
        new_family = (f.get("new_specialty_family") or "").strip()
        if new_name:
            existing = Specialty.query.filter(db.func.lower(Specialty.name) == new_name.lower()).first()
            if not existing:
                existing = Specialty(name=new_name, category=(new_family or None))
                db.session.add(existing)
                db.session.flush()
            spec_ids.append(existing.id)

        # Déterminer la spécialité primaire si absente
        primary_spec_id = f.get("primary_specialty_id", type=int)
        if primary_spec_id:
            professional.primary_specialty_id = primary_spec_id
        elif not getattr(professional, "primary_specialty_id", None) and spec_ids:
            professional.primary_specialty_id = spec_ids[0]

        if spec_ids:
            professional.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all()

        # Synchroniser le champ legacy "specialty" si besoin
        if professional.primary_specialty_id and not (professional.specialty or "").strip():
            ps = db.session.get(Specialty, professional.primary_specialty_id)
            if ps:
                professional.specialty = ps.name

        # Helpers robustes
        def _normalize_num_string(v_str):
            v = (v_str or "").strip()
            if not v:
                return v
            v = v.replace(" ", "").replace("MAD", "").replace("mad", "")
            v = v.replace(",", ".")
            return v

        def parse_int_or_keep(v_str, old_val, default_if_invalid=None):
            v = _normalize_num_string(v_str)
            if v == "":
                return old_val
            try:
                return int(float(v))
            except ValueError:
                return old_val if old_val is not None else default_if_invalid

        def parse_float_or_keep(v_str, old_val, default_if_invalid=None):
            v = _normalize_num_string(v_str)
            if v == "":
                return old_val
            try:
                return float(v)
            except ValueError:
                return old_val if old_val is not None else default_if_invalid

        # Coordonnées
        professional.latitude  = parse_float_or_keep(f.get("latitude"),  getattr(professional, "latitude", None))
        professional.longitude = parse_float_or_keep(f.get("longitude"), getattr(professional, "longitude", None))

        # 🔐 Colonnes NOT NULL
        professional.consultation_fee = parse_int_or_keep(
            f.get("consultation_fee"),
            getattr(professional, "consultation_fee", 0),
            default_if_invalid=0
        )
        if professional.consultation_fee is None or professional.consultation_fee < 0:
            professional.consultation_fee = 0

        professional.consultation_duration_minutes = parse_int_or_keep(
            f.get("consultation_duration_minutes"),
            getattr(professional, "consultation_duration_minutes", 45),
            default_if_invalid=45
        ) or 45

        professional.buffer_between_appointments_minutes = parse_int_or_keep(
            f.get("buffer_between_appointments_minutes"),
            getattr(professional, "buffer_between_appointments_minutes", 15),
            default_if_invalid=15
        ) or 15

        # Types de consultation (CSV)
        posted_types = [t for t in f.getlist("consultation_types") if t]
        if posted_types:
            professional.consultation_types = ",".join(sorted(set(posted_types)))

        # Réseaux sociaux
        old_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        professional.facebook_url  = (f.get("facebook_url", "") or None)
        professional.instagram_url = (f.get("instagram_url", "") or None)
        professional.tiktok_url    = (f.get("tiktok_url", "") or None)
        professional.youtube_url   = (f.get("youtube_url", "") or None)
        new_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        if new_links != old_links:
            professional.social_links_approved = False

        # 3) Première sauvegarde ?
        if professional.id is None:
            db.session.add(professional)

        try:
            db.session.commit()
            flash("Profil mis à jour.", "success")
            return redirect(url_for("professional_dashboard"))
        except IntegrityError:
            db.session.rollback()
            current_app.logger.exception("IntegrityError on professional profile update")
            flash("Impossible d'enregistrer : certaines valeurs sont invalides ou manquantes.", "danger")
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("DB error on professional profile update")
            flash("Erreur technique lors de l'enregistrement. Réessayez.", "danger")

    # GET
    cities = _ui_cities()
    specialties = _ui_specialties()
    families = _ui_families_rows()

    return render_or_text(
        "professional_edit_profile.html",
        "Éditer profil pro",
        professional=professional,
        cities=cities,
        families=families,
        specialties=specialties
    )


# ===== RDV côté PRO : liste + filtres =====
@app.route("/professional/appointments", methods=["GET"], endpoint="professional_appointments")
@login_required
def professional_appointments():
    from datetime import datetime
    if getattr(current_user, "user_type", None) != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé"); return redirect(url_for("professional_dashboard"))

    status = (request.args.get("status") or "all").strip()
    scope  = (request.args.get("scope")  or "upcoming").strip()

    q = Appointment.query.filter_by(professional_id=pro.id)
    now = datetime.utcnow()

    # Supporte appointment_date OU start_at selon ton modèle
    if hasattr(Appointment, "appointment_date"):
        date_col = Appointment.appointment_date
    else:
        date_col = getattr(Appointment, "start_at", None)

    if scope == "upcoming" and date_col is not None:
        q = q.filter(date_col >= now)
    elif scope == "past" and date_col is not None:
        q = q.filter(date_col < now)

    # Statuts utilisés dans tes templates
    if status in ("en_attente", "confirme", "annule"):
        q = q.filter_by(status=status)

    # Tri robuste
    if date_col is not None:
        q = q.order_by(date_col.desc())
    else:
        q = q.order_by(Appointment.id.desc())

    appointments = q.all()

    return render_or_text(
        "professional_appointments.html",
        "Rendez-vous pro",
        appointments=appointments,
        status=status,
        scope=scope
    )

# ===== Action RDV (confirmer / annuler / etc.) =====
@app.route(
    "/professional/appointments/<int:appointment_id>/<action>",
    methods=["POST"],
    endpoint="professional_appointment_action"
)
@login_required
def professional_appointment_action(appointment_id: int, action: str):
    # Pas de dépendance à _current_professional_or_403 pour éviter les NameError
    if getattr(current_user, "user_type", None) != "professional":
        abort(403)

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé", "danger")
        return redirect(url_for("professional_dashboard"))

    ap = Appointment.query.get_or_404(appointment_id)
    if ap.professional_id != pro.id:
        abort(403)

    act = (action or "").strip().lower()
    status_map = {
        # confirmer
        "confirm": "confirme", "confirmed": "confirme", "accept": "confirme", "approve": "confirme",
        # annuler
        "cancel": "annule", "canceled": "annule", "annuler": "annule", "reject": "annule", "refuse": "annule",
        # états optionnels si tu veux t’en servir plus tard
        "pending": "en_attente", "request": "en_attente", "requested": "en_attente",
        "done": "termine", "complete": "termine", "finish": "termine",
        "noshow": "no_show", "no-show": "no_show"
    }
    new_status = status_map.get(act)
    if not new_status:
        flash("Action inconnue.", "warning")
        return redirect(request.referrer or url_for("professional_appointments"))

    ap.status = new_status
    # Tente de mettre à jour updated_at si présent
    try:
        from datetime import datetime as _dt
        if hasattr(ap, "updated_at"):
            ap.updated_at = _dt.utcnow()
    except Exception:
        pass

    db.session.commit()
    flash("Rendez-vous mis à jour.", "success")
    return redirect(request.referrer or url_for("professional_appointments"))


# ====== Entrée "Dossier patient" (alias smart) ======
@app.route("/pro/patient", methods=["GET"], endpoint="pro_patient_entry")
@login_required
def pro_patient_entry():
    from sqlalchemy import or_
    if current_user.user_type != "professional":
        flash("Accès réservé aux professionnels.", "warning")
        return redirect(url_for("index"))

    pro = Professional.query.filter_by(name=current_user.username).first()
    if not pro:
        flash("Profil professionnel non trouvé", "danger")
        return redirect(url_for("professional_dashboard"))

    patient_id = request.args.get("id", type=int) or request.args.get("patient_id", type=int)
    q = (request.args.get("q") or "").strip()

    # 1) Accès direct par id
    if patient_id:
        link = (
            db.session.query(Appointment.id)
            .filter(Appointment.professional_id == pro.id, Appointment.patient_id == patient_id)
            .first()
        )
        if link:
            return redirect(url_for("pro_patient_detail", patient_id=patient_id))
        else:
            flash("Ce patient n'est pas lié à vos rendez-vous.", "warning")
            return redirect(url_for("pro_patients"))

    # 2) Recherche par q
    if q:
        like = f"%{q}%"
        subq = (
            db.session.query(Appointment.patient_id.label("pid"))
            .filter(Appointment.professional_id == pro.id)
            .group_by(Appointment.patient_id)
            .subquery()
        )
        matches = (
            db.session.query(User.id)
            .join(subq, subq.c.pid == User.id)
            .filter(
                or_(
                    User.username.ilike(like),
                    User.full_name.ilike(like),
                    User.email.ilike(like),
                    User.phone.ilike(like),
                )
            )
            .order_by(User.id.desc())
            .all()
        )
        ids = [m.id for m in matches]
        if len(ids) == 1:
            return redirect(url_for("pro_patient_detail", patient_id=ids[0]))
        return redirect(url_for("pro_patients", q=q))

    return redirect(url_for("pro_patients"))


# =========================
#   BUREAU VIRTUEL — PRO
# =========================
@app.route("/pro-office/", methods=["GET"], endpoint="pro_office_index")
@login_required
def pro_office_index():
    from datetime import datetime, time as _Time
    if getattr(current_user, "user_type", None) != "professional":
        abort(403)

    pro = (
        Professional.query
        .filter(
            (Professional.name == (getattr(current_user, "full_name", "") or "")) |
            (Professional.name == (getattr(current_user, "username", "") or ""))
        )
        .first()
    )
    if not pro:
        abort(403)

    next_sessions = []
    upcoming_count = 0
    unread_messages = 0
    pending_payments = 0

    now = datetime.utcnow()
    PENDING = {"requested", "pending", "en_attente", "planifie"}
    CANCELLED = {"cancelled", "canceled", "refused", "rejected", "declined", "annule", "annulé", "no_show"}
    CONFIRMED = {"confirmed", "accepted", "approved", "valide", "validated", "confirmé", "confirme"}

    def _extract_dt(obj):
        for attr in ("start_at", "appointment_date", "scheduled_at", "start_time_dt"):
            v = getattr(obj, attr, None)
            if isinstance(v, datetime):
                return v
        d = getattr(obj, "date", None) or getattr(obj, "appointment_day", None)
        t = getattr(obj, "time", None) or getattr(obj, "appointment_time", None) or getattr(obj, "start_time", None)
        if d and t:
            try:
                if isinstance(t, str) and ":" in t:
                    hh, mm = t.split(":")[:2]
                    from datetime import time as _T
                    t = _T(int(hh), int(mm))
                return datetime.combine(d, t)
            except Exception:
                pass
        if d:
            try:
                from datetime import time as _T
                return datetime.combine(d, _T(12, 0))
            except Exception:
                pass
        return None

    def _is_confirmed(obj):
        st = getattr(obj, "status", None)
        if st is None:
            return True
        s = str(st).strip().lower()
        if s in CANCELLED:
            return False
        if s in PENDING:
            return False
        if s in CONFIRMED:
            return True
        return True

    # Séances/RDV à venir
    try:
        fused = []

        # TherapySession
        try:
            q = TherapySession.query.filter(TherapySession.professional_id == pro.id)
            if hasattr(TherapySession, "start_at"):
                q = q.filter(TherapySession.start_at >= now).order_by(TherapySession.start_at.asc())
            else:
                q = q.order_by(TherapySession.id.desc())
            for s in q.limit(100).all():
                dtv = _extract_dt(s)
                if not dtv or dtv < now or not _is_confirmed(s):
                    continue
                pname = "—"
                try:
                    pat = getattr(s, "patient", None)
                    if not pat and getattr(s, "patient_id", None):
                        pat = User.query.get(s.patient_id)
                    pname = getattr(pat, "full_name", None) or getattr(pat, "name", None) or getattr(pat, "username", None) or "—"
                except Exception:
                    pass
                fused.append({
                    "when_dt": dtv,
                    "when": dtv.strftime("%d/%m/%Y %H:%M"),
                    "patient_name": pname,
                    "where": getattr(s, "location", None) or getattr(s, "place", None) or getattr(s, "address", None),
                    "meet_url": getattr(s, "meet_url", None),
                    "link": getattr(s, "meet_url", None),
                })
        except Exception:
            pass

        # Appointment
        try:
            q = Appointment.query.filter(Appointment.professional_id == pro.id)
            if hasattr(Appointment, "appointment_date"):
                q = q.filter(Appointment.appointment_date >= now).order_by(Appointment.appointment_date.asc())
            elif hasattr(Appointment, "start_at"):
                q = q.filter(Appointment.start_at >= now).order_by(Appointment.start_at.asc())
            else:
                q = q.order_by(Appointment.id.desc())
            for a in q.limit(100).all():
                dtv = _extract_dt(a)
                if not dtv or dtv < now or not _is_confirmed(a):
                    continue
                pname = "—"
                try:
                    pat = getattr(a, "patient", None)
                    if not pat and getattr(a, "patient_id", None):
                        pat = User.query.get(a.patient_id)
                    pname = getattr(pat, "full_name", None) or getattr(pat, "name", None) or getattr(pat, "username", None) or "—"
                except Exception:
                    pass
                meet_url = (
                    getattr(a, "meet_url", None)
                    or getattr(a, "video_link", None)
                    or getattr(a, "meeting_link", None)
                    or None
                )
                fused.append({
                    "when_dt": dtv,
                    "when": dtv.strftime("%d/%m/%Y %H:%M"),
                    "patient_name": pname,
                    "where": getattr(a, "location", None) or getattr(a, "place", None) or getattr(a, "address", None),
                    "meet_url": meet_url,
                    "link": meet_url,
                })
        except Exception:
            pass

        fused.sort(key=lambda x: x["when_dt"])
        upcoming_count = len(fused)
        next_sessions = fused[:5]
    except Exception:
        next_sessions = []
        upcoming_count = 0

    # Messages non lus (dernier message du fil non envoyé par le pro)
    try:
        cnt = 0
        threads = (MessageThread.query
                   .filter_by(professional_id=pro.id)
                   .order_by(MessageThread.updated_at.desc().nullslast())
                   .limit(50).all())
        for th in threads:
            last = (Message.query
                    .filter_by(thread_id=getattr(th, "id", None))
                    .order_by(Message.created_at.desc())
                    .first())
            if not last:
                continue
            sender_id = getattr(last, "sender_user_id", None) or getattr(last, "sender_id", None)
            if sender_id and sender_id != getattr(current_user, "id", None):
                cnt += 1
        unread_messages = cnt
    except Exception:
        unread_messages = 0

    # Paiements en attente
    try:
        if "Invoice" in globals():
            q = Invoice.query.filter_by(professional_id=pro.id)
            if hasattr(Invoice, "status"):
                q = q.filter(Invoice.status.in_(["issued", "unpaid", "due"]))
            pending_payments = q.count()
        else:
            pending_payments = 0
    except Exception:
        pending_payments = 0

    return render_or_text("pro/office.html", "Bureau virtuel",
                          next_sessions=next_sessions,
                          upcoming_count=upcoming_count,
                          unread_messages=unread_messages,
                          pending_payments=pending_payments)


@app.route("/pro/desk", endpoint="pro_desk")
@login_required
def pro_desk():
    pro = _current_professional_or_403()
    latest_threads = MessageThread.query.filter_by(professional_id=pro.id).order_by(MessageThread.id.desc()).limit(10).all()
    latest_sessions = TherapySession.query.filter_by(professional_id=pro.id).order_by(TherapySession.start_at.desc()).limit(10).all()
    latest_invoices = Invoice.query.filter_by(professional_id=pro.id).order_by(Invoice.issued_at.desc()).limit(10).all()
    return render_or_text("pro/desk.html", "Bureau virtuel",
                          professional=pro, threads=latest_threads, sessions=latest_sessions, invoices=latest_invoices)


@app.route("/pro/patients", methods=["GET"], endpoint="pro_patients")
@login_required
def pro_patients():
    """
    Liste des patients du pro basée sur TOUT lien existant :
    - Appointment.professional_id
    - TherapySession.professional_id
    - MessageThread.professional_id (supporte patient_id OU patient_user_id)
    - ExerciseAssignment.professional_id (patient_id ou patient_user_id)
    - PatientCase.professional_id (patient_user_id)
    On renvoie rows = [(User, total_rdv, confirme_count, last_date), ...]
    """
    from sqlalchemy import or_, func, case
    from datetime import datetime

    if getattr(current_user, "user_type", None) != "professional":
        flash("Accès réservé aux professionnels.", "warning")
        return redirect(url_for("index"))

    # Résoudre le pro de façon robuste (même logique que le reste de l'app)
    pro = (
        Professional.query
        .filter(
            (Professional.name == (getattr(current_user, "full_name", "") or "")) |
            (Professional.name == (getattr(current_user, "username", "") or ""))
        )
        .first()
    ) or Professional.query.filter_by(name=current_user.username).first()

    if not pro:
        flash("Profil professionnel non trouvé", "danger")
        return redirect(url_for("professional_dashboard"))

    q_text = (request.args.get("q") or "").strip()
    page = max(1, request.args.get("page", type=int) or 1)
    per_page = 20

    # ---- 1) Collecte de tous les patient_ids liés au pro (set())
    patient_ids = set()

    # Appointments (source principale)
    try:
        ids = [pid for (pid,) in db.session.query(Appointment.patient_id)
                                   .filter(Appointment.professional_id == pro.id,
                                           Appointment.patient_id.isnot(None)).distinct().all()]
        patient_ids.update(ids)
    except Exception:
        pass

    # TherapySession
    try:
        ids = [pid for (pid,) in db.session.query(TherapySession.patient_id)
                                   .filter(TherapySession.professional_id == pro.id,
                                           TherapySession.patient_id.isnot(None)).distinct().all()]
        patient_ids.update(ids)
    except Exception:
        pass

    # MessageThread — compat champs (patient_id OU patient_user_id)
    try:
        if hasattr(MessageThread, "patient_id"):
            ids = [pid for (pid,) in db.session.query(MessageThread.patient_id)
                                       .filter(MessageThread.professional_id == pro.id,
                                               MessageThread.patient_id.isnot(None)).distinct().all()]
            patient_ids.update(ids)
    except Exception:
        pass
    try:
        if hasattr(MessageThread, "patient_user_id"):
            ids = [pid for (pid,) in db.session.query(MessageThread.patient_user_id)
                                       .filter(MessageThread.professional_id == pro.id,
                                               MessageThread.patient_user_id.isnot(None)).distinct().all()]
            patient_ids.update(ids)
    except Exception:
        pass

    # ExerciseAssignment — compat (patient_id / patient_user_id)
    try:
        if hasattr(ExerciseAssignment, "patient_id"):
            ids = [pid for (pid,) in db.session.query(ExerciseAssignment.patient_id)
                                       .filter(ExerciseAssignment.professional_id == pro.id,
                                               ExerciseAssignment.patient_id.isnot(None)).distinct().all()]
            patient_ids.update(ids)
    except Exception:
        pass
    try:
        if hasattr(ExerciseAssignment, "patient_user_id"):
            ids = [pid for (pid,) in db.session.query(ExerciseAssignment.patient_user_id)
                                       .filter(ExerciseAssignment.professional_id == pro.id,
                                               ExerciseAssignment.patient_user_id.isnot(None)).distinct().all()]
            patient_ids.update(ids)
    except Exception:
        pass

    # PatientCase (patient_user_id)
    try:
        if "PatientCase" in globals() and hasattr(PatientCase, "patient_user_id"):
            ids = [pid for (pid,) in db.session.query(PatientCase.patient_user_id)
                                       .filter(PatientCase.professional_id == pro.id,
                                               PatientCase.patient_user_id.isnot(None)).distinct().all()]
            patient_ids.update(ids)
    except Exception:
        pass

    if not patient_ids:
        # Vue vide, mais on garde la forme
        return render_or_text(
            "pro/patients.html", "Mes patients",
            rows=[], q=q_text, page=page, per_page=per_page, total=0, professional=pro
        )

    # ---- 2) Option de filtre texte q sur User
    users_q = User.query.filter(User.id.in_(patient_ids), User.user_type == "patient")
    if q_text:
        like = f"%{q_text}%"
        users_q = users_q.filter(or_(
            User.username.ilike(like),
            User.full_name.ilike(like),
            User.email.ilike(like),
            User.phone.ilike(like),
        ))
    users = users_q.all()
    if not users:
        return render_or_text(
            "pro/patients.html", "Mes patients",
            rows=[], q=q_text, page=page, per_page=per_page, total=0, professional=pro
        )

    filtered_ids = [u.id for u in users]

    # ---- 3) Agrégations RDV (total, confirmés, dernière date RDV)
    # Statuts confirmés compatibles (selon ta base)
    CONF = {"confirme", "confirmé", "confirmed"}

    # total_rdv & confirme_count & last_rdv_dt
    ap_agg = {}
    try:
        # total
        rows_total = db.session.query(
            Appointment.patient_id,
            func.count(Appointment.id)
        ).filter(
            Appointment.professional_id == pro.id,
            Appointment.patient_id.in_(filtered_ids)
        ).group_by(Appointment.patient_id).all()

        for pid, cnt in rows_total:
            ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
            ap_agg[pid]["total"] = int(cnt or 0)

        # confirmés
        try:
            rows_conf = db.session.query(
                Appointment.patient_id,
                func.count(Appointment.id)
            ).filter(
                Appointment.professional_id == pro.id,
                Appointment.patient_id.in_(filtered_ids),
                func.lower(func.coalesce(Appointment.status, "")).
                    in_([s.lower() for s in CONF])
            ).group_by(Appointment.patient_id).all()
            for pid, cnt in rows_conf:
                ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
                ap_agg[pid]["conf"] = int(cnt or 0)
        except Exception:
            pass

        # last_date à partir d'appointment_date
        try:
            rows_last = db.session.query(
                Appointment.patient_id,
                func.max(Appointment.appointment_date)
            ).filter(
                Appointment.professional_id == pro.id,
                Appointment.patient_id.in_(filtered_ids)
            ).group_by(Appointment.patient_id).all()
            for pid, dtv in rows_last:
                ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
                ap_agg[pid]["last"] = dtv
        except Exception:
            pass
    except Exception:
        pass

    # ---- 4) Dernière interaction via Session / MessageThread
    # TherapySession.start_at
    try:
        rows_last_sess = db.session.query(
            TherapySession.patient_id,
            func.max(TherapySession.start_at)
        ).filter(
            TherapySession.professional_id == pro.id,
            TherapySession.patient_id.in_(filtered_ids)
        ).group_by(TherapySession.patient_id).all()
        for pid, dtv in rows_last_sess:
            ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
            if dtv and (ap_agg[pid]["last"] is None or (isinstance(ap_agg[pid]["last"], datetime) and dtv > ap_agg[pid]["last"])):
                ap_agg[pid]["last"] = dtv
    except Exception:
        pass

    # MessageThread.updated_at (support patient_id OU patient_user_id)
    # patient_id
    try:
        if hasattr(MessageThread, "patient_id"):
            rows_last_th = db.session.query(
                MessageThread.patient_id,
                func.max(MessageThread.updated_at)
            ).filter(
                MessageThread.professional_id == pro.id,
                MessageThread.patient_id.in_(filtered_ids)
            ).group_by(MessageThread.patient_id).all()
            for pid, dtv in rows_last_th:
                ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
                if dtv and (ap_agg[pid]["last"] is None or (isinstance(ap_agg[pid]["last"], datetime) and dtv > ap_agg[pid]["last"])):
                    ap_agg[pid]["last"] = dtv
    except Exception:
        pass
    # patient_user_id
    try:
        if hasattr(MessageThread, "patient_user_id"):
            rows_last_th2 = db.session.query(
                MessageThread.patient_user_id,
                func.max(MessageThread.updated_at)
            ).filter(
                MessageThread.professional_id == pro.id,
                MessageThread.patient_user_id.in_(filtered_ids)
            ).group_by(MessageThread.patient_user_id).all()
            for pid, dtv in rows_last_th2:
                ap_agg.setdefault(pid, {"total": 0, "conf": 0, "last": None})
                if dtv and (ap_agg[pid]["last"] is None or (isinstance(ap_agg[pid]["last"], datetime) and dtv > ap_agg[pid]["last"])):
                    ap_agg[pid]["last"] = dtv
    except Exception:
        pass

    # ---- 5) Construire rows et trier par dernière interaction desc
    rows_py = []
    for u in users:
        agg = ap_agg.get(u.id, {"total": 0, "conf": 0, "last": None})
        rows_py.append((u, int(agg.get("total", 0) or 0), int(agg.get("conf", 0) or 0), agg.get("last", None)))

    rows_py.sort(key=lambda t: (t[3] is not None, t[3]), reverse=True)

    # ---- 6) Pagination côté Python
    total = len(rows_py)
    start = (page - 1) * per_page
    end = start + per_page
    page_rows = rows_py[start:end]

    return render_or_text(
        "pro/patients.html",
        "Mes patients",
        rows=page_rows,
        q=q_text,
        page=page,
        per_page=per_page,
        total=total,
        professional=pro
    )


@app.route("/pro/patients/<int:patient_id>", methods=["GET","POST"], endpoint="pro_patient_detail")
@login_required
def pro_patient_detail(patient_id: int):
    pro = _current_professional_or_403()
    patient = User.query.get_or_404(patient_id)
    if patient.user_type != "patient":
        abort(404)
    profile = PatientProfile.query.filter_by(user_id=patient.id).first()
    medhist = MedicalHistory.query.filter_by(patient_id=patient.id, professional_id=pro.id).order_by(MedicalHistory.id.desc()).first()
    sessions = TherapySession.query.filter_by(patient_id=patient.id, professional_id=pro.id).order_by(TherapySession.start_at.desc()).all()
    thread = MessageThread.query.filter_by(patient_id=patient.id, professional_id=pro.id).first()

    if request.method == "POST":
        summary = (request.form.get("summary") or "").strip()
        custom = (request.form.get("custom_fields") or "").strip()
        if not medhist:
            medhist = MedicalHistory(patient_id=patient.id, professional_id=pro.id, summary=summary, custom_fields=custom or None)
            db.session.add(medhist)
        else:
            medhist.summary = summary or medhist.summary
            medhist.custom_fields = custom or medhist.custom_fields
        db.session.commit()
        flash("Dossier patient mis à jour.", "success")
        return redirect(url_for("pro_patient_detail", patient_id=patient.id))

    return render_or_text("pro/patient_detail.html", "Dossier patient",
                          professional=pro, patient=patient, profile=profile, medhist=medhist, sessions=sessions, thread=thread)


@app.route("/pro/threads/<int:patient_id>", methods=["GET","POST"], endpoint="pro_thread")
@login_required
def pro_thread(patient_id: int):
    pro = _current_professional_or_403()
    patient = User.query.get_or_404(patient_id)
    if patient.user_type != "patient":
        abort(404)
    thread = MessageThread.query.filter_by(patient_id=patient.id, professional_id=pro.id).first()
    if not thread:
        thread = MessageThread(patient_id=patient.id, professional_id=pro.id, is_anonymous=False)
        db.session.add(thread); db.session.commit()

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        file = request.files.get("attachment")
        audio = request.files.get("audio")
        attachment = None
        if file:
            try:
                name = _save_attachment(file)
                attachment = FileAttachment(
                    file_url=f"/u/attachments/{name}",
                    file_name=file.filename,
                    content_type=file.mimetype,
                    size_bytes=file.content_length or 0,
                    owner_user_id=current_user.id,
                    patient_id=patient.id
                )
                db.session.add(attachment); db.session.flush()
            except Exception as e:
                current_app.logger.warning("Upload pièce jointe: %s", e)
                flash("Pièce jointe non acceptée.", "warning")
        audio_url = None
        if audio:
            try:
                name = _save_attachment(audio)
                audio_url = f"/u/attachments/{name}"
            except Exception:
                flash("Audio non accepté.", "warning")
        msg = Message(thread_id=thread.id, sender_id=current_user.id, body=body or None,
                      attachment_id=attachment.id if attachment else None, audio_url=audio_url)
        db.session.add(msg); db.session.commit()

        try:
            if patient.email:
                safe_send_email(patient.email, f"{BRAND_NAME} — Nouveau message", f"Le professionnel vous a écrit sur {BRAND_NAME}.")
        except Exception:
            pass

        return redirect(url_for("pro_thread", patient_id=patient.id))

    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.created_at.asc()).all()
    return render_or_text("pro/thread.html", "Messagerie sécurisée",
                          professional=pro, patient=patient, thread=thread, messages=messages)


# Index messagerie existant
@app.route("/messages", endpoint="messages_index")
@login_required
def messages_index():
    if current_user.user_type == "professional":
        return redirect(url_for("pro_patients"))
    else:
        threads = MessageThread.query.filter_by(patient_id=current_user.id)\
                                     .order_by(MessageThread.updated_at.desc().nullslast()).all()
        return render_or_text("patient/messages_index.html", "Messagerie", threads=threads)


# Alias pour éviter le 404 quand un lien pointe sur /pro/messages
@app.get("/pro/messages")
@login_required
def pro_messages_alias():
    try:
        return redirect(url_for("messages_index"))
    except Exception:
        return redirect("/messages")


@app.route("/pro/billing", methods=["GET"], endpoint="pro_billing")
@login_required
def pro_billing():
    if getattr(current_user, "user_type", None) != "professional":
        abort(403)

    current_plan = {
        "name": "Essentiel",
        "price": 0,
        "currency": "MAD",
        "period": "mois",
        "features": ["Profil public", "Prise de RDV", "Agenda basique"],
        "renews_at": None,
        "status": "actif",
    }

    payment_method = {
        "brand": "Visa",
        "last4": "4242",
        "exp": "08/27",
    }

    invoices = []

    return render_or_text(
        "pro_billing.html",
        "Facturation",
        current_plan=current_plan,
        payment_method=payment_method,
        invoices=invoices
    )


# --- Sessions & notes
@app.route("/pro/sessions", methods=["GET","POST"], endpoint="pro_sessions")
@login_required
def pro_sessions():
    from datetime import datetime
    pro = _current_professional_or_403()
    if request.method == "POST":
        patient_id = request.form.get("patient_id", type=int)
        start_at = request.form.get("start_at", "")
        mode = (request.form.get("mode") or "cabinet").strip()
        meet_url = (request.form.get("meet_url") or "").strip() or None
        try:
            dt = datetime.fromisoformat(start_at)
        except Exception:
            flash("Date/heure invalide (ISO 8601 attendu).", "danger")
            return redirect(url_for("pro_sessions"))
        if not User.query.get(patient_id):
            flash("Patient introuvable.", "danger")
            return redirect(url_for("pro_sessions"))
        s = TherapySession(patient_id=patient_id, professional_id=pro.id, start_at=dt, mode=mode, meet_url=meet_url, status="planifie")
        db.session.add(s); db.session.commit()
        flash("Séance planifiée.", "success")
        return redirect(url_for("pro_sessions"))

    sessions = TherapySession.query.filter_by(professional_id=pro.id).order_by(TherapySession.start_at.desc()).all()
    patients = User.query.filter(User.user_type == "patient").order_by(User.username.asc()).all()
    return render_or_text("pro/sessions.html", "Séances", sessions=sessions, patients=patients, professional=pro)


@app.route("/pro/sessions/<int:session_id>", methods=["GET","POST"], endpoint="pro_session_detail")
@login_required
def pro_session_detail(session_id: int):
    pro = _current_professional_or_403()
    s = TherapySession.query.get_or_404(session_id)
    if s.professional_id != pro.id:
        abort(403)
    if request.method == "POST":
        content = (request.form.get("content") or "").strip()
        visibility = (request.form.get("visibility") or "pro").strip()
        n = SessionNote(session_id=s.id, author_id=current_user.id, visibility=visibility, content=content)
        db.session.add(n); db.session.commit()
        flash("Note ajoutée.", "success")
        return redirect(url_for("pro_session_detail", session_id=s.id))
    notes = SessionNote.query.filter_by(session_id=s.id).order_by(SessionNote.created_at.asc()).all()
    return render_or_text("pro/session_detail.html", "Détail séance", session=s, notes=notes, professional=pro)


# --- Bibliothèque d’exercices
@app.route("/pro/library", methods=["GET","POST"], endpoint="pro_library")
@login_required
def pro_library():
    from sqlalchemy import or_
    from datetime import datetime
    pro = _current_professional_or_403()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Titre requis.", "danger"); return redirect(url_for("pro_library"))
        ex = Exercise(
            owner_id=current_user.id, professional_id=pro.id, title=title,
            description=(request.form.get("description") or "").strip() or None,
            family=(request.form.get("family") or "").strip() or None,
            type=(request.form.get("type") or "").strip() or "exercice",
            technique=(request.form.get("technique") or "").strip() or None,
            content_format=(request.form.get("content_format") or "").strip() or "texte",
            text_content=(request.form.get("text_content") or "").strip() or None,
            visibility=(request.form.get("visibility") or "private").strip(),
            is_approved=False
        )
        file = request.files.get("file")
        if file:
            try:
                name = _save_attachment(file)
                ex.file_url = f"/u/attachments/{name}"
            except Exception:
                flash("Fichier non accepté.", "warning")
        db.session.add(ex); db.session.commit()
        flash("Exercice créé.", "success")
        return redirect(url_for("pro_library"))

    q = Exercise.query.filter(
        or_(Exercise.visibility == "public", Exercise.owner_id == current_user.id, Exercise.professional_id == pro.id)
    ).order_by(Exercise.created_at.desc())
    exercises = q.all()
    return render_or_text("pro/library.html", "Bibliothèque", exercises=exercises, professional=pro)


# --- Assignations d’exercices aux patients
@app.route("/pro/assign", methods=["POST"], endpoint="pro_assign_exercise")
@login_required
def pro_assign_exercise():
    from datetime import datetime
    pro = _current_professional_or_403()
    exercise_id = request.form.get("exercise_id", type=int)
    patient_id = request.form.get("patient_id", type=int)
    due_date = request.form.get("due_date")
    if not (exercise_id and patient_id):
        abort(400)
    ex = Exercise.query.get_or_404(exercise_id)
    if ex.visibility not in ("public", "my_patients") and ex.owner_id != current_user.id and ex.professional_id != pro.id:
        abort(403)
    assign = ExerciseAssignment(exercise_id=exercise_id, patient_id=patient_id, professional_id=pro.id,
                                status="assigned", due_date=datetime.fromisoformat(due_date).date() if due_date else None)
    db.session.add(assign); db.session.commit()
    flash("Exercice assigné au patient.", "success")
    return redirect(request.referrer or url_for("pro_library"))


# --- Factures & paiements
@app.route("/pro/invoices", methods=["GET","POST"], endpoint="pro_invoices")
@login_required
def pro_invoices():
    from datetime import datetime
    pro = _current_professional_or_403()
    if request.method == "POST":
        patient_id = request.form.get("patient_id", type=int)
        amount = request.form.get("amount", type=float)
        desc = (request.form.get("description") or "").strip() or None
        inv = Invoice(patient_id=patient_id, professional_id=pro.id, amount=amount, description=desc, status="issued", issued_at=datetime.utcnow())
        db.session.add(inv); db.session.commit()
        flash("Facture émise.", "success")
        return redirect(url_for("pro_invoices"))
    invoices = Invoice.query.filter_by(professional_id=pro.id).order_by(Invoice.issued_at.desc()).all()
    patients = User.query.filter(User.user_type == "patient").all()
    return render_or_text("pro/invoices.html", "Factures", invoices=invoices, patients=patients, professional=pro)


@app.route("/pro/invoices/<int:invoice_id>/pay", methods=["POST"], endpoint="pro_invoice_pay")
@login_required
def pro_invoice_pay(invoice_id: int):
    from datetime import datetime
    pro = _current_professional_or_403()
    inv = Invoice.query.get_or_404(invoice_id)
    if inv.professional_id != pro.id:
        abort(403)
    method = (request.form.get("method") or "cash").strip()
    amount = float(request.form.get("amount") or inv.amount)
    p = Payment(invoice_id=inv.id, method=method, amount=amount, status="succeeded", paid_at=datetime.utcnow())
    inv.status = "paid"
    db.session.add(p); db.session.commit()
    flash("Paiement enregistré.", "success")
    return redirect(url_for("pro_invoices"))


@app.route("/pro/stats", endpoint="pro_stats")
@login_required
def pro_stats():
    pro = _current_professional_or_403()
    total_sessions = TherapySession.query.filter_by(professional_id=pro.id).count()
    total_minutes = 0
    for s in TherapySession.query.filter_by(professional_id=pro.id).all():
        if s.end_at and s.start_at:
            total_minutes += int((s.end_at - s.start_at).total_seconds() // 60)
    total_invoices = Invoice.query.filter_by(professional_id=pro.id).count()
    revenue = db.session.query(db.func.coalesce(db.func.sum(Invoice.amount), 0.0)).filter_by(professional_id=pro.id, status="paid").scalar()
    return render_or_text("pro/stats.html", "Statistiques",
                          stats={"sessions": total_sessions, "minutes": total_minutes, "invoices": total_invoices, "revenue": revenue},
                          professional=pro)


@app.route("/pro/support", methods=["GET","POST"], endpoint="pro_support")
@login_required
def pro_support():
    pro = _current_professional_or_403()
    if request.method == "POST":
        subj = (request.form.get("subject") or "").strip()
        body = (request.form.get("body") or "").strip()
        st = SupportTicket(user_id=current_user.id, professional_id=pro.id, subject=subj, body=body, status="open", priority="normal")
        db.session.add(st); db.session.commit()
        flash("Ticket créé.", "success")
        return redirect(url_for("pro_support"))
    tickets = SupportTicket.query.filter_by(professional_id=pro.id).order_by(SupportTicket.created_at.desc()).all()
    guides = Guide.query.order_by(Guide.created_at.desc()).all()
    return render_or_text("pro/support.html", "Support & Guides", tickets=tickets, guides=guides, professional=pro)
# ====== Dossier patient (auto-prérempli) =====================================
@app.route("/pro/patients/<int:patient_id>/dossier", methods=["GET","POST"], endpoint="pro_patient_dossier")
@login_required
def pro_patient_dossier(patient_id: int):
    pro = _current_professional_or_403()
    user = User.query.get_or_404(patient_id)
    if user.user_type != "patient": abort(404)

    case, profile = _ensure_patient_case(pro.id, user.id)
    medhist = None
    try:
        medhist = (MedicalHistory.query
                   .filter_by(patient_id=user.id, professional_id=pro.id)
                   .order_by(MedicalHistory.id.desc()).first())
    except Exception:
        pass

    if request.method == "POST":
        f = request.form
        if profile:
            profile.full_name = f.get("full_name") or profile.full_name
            profile.email = f.get("email") or profile.email
            profile.phone = f.get("phone") or profile.phone
            profile.address = f.get("address") or profile.address
        if case:
            case.display_name = f.get("display_name") or case.display_name or None
            case.is_anonymous = (f.get("is_anonymous") == "on")
            if hasattr(case, "notes"): case.notes = f.get("notes") or case.notes
        summary = (f.get("summary") or "").strip()
        diagnostics = (f.get("diagnostics") or "").strip()
        try:
            if "MedicalHistory" in globals():
                if not medhist:
                    medhist = MedicalHistory(patient_id=user.id, professional_id=pro.id,
                                             summary=summary or None, custom_fields=diagnostics or None)
                    db.session.add(medhist)
                else:
                    if summary: medhist.summary = summary
                    if diagnostics: medhist.custom_fields = diagnostics
        except Exception:
            pass
        try:
            db.session.commit(); flash("Dossier patient enregistré.", "success")
        except Exception:
            db.session.rollback(); flash("Impossible d'enregistrer le dossier.", "danger")
        return redirect(url_for("pro_patient_dossier", patient_id=user.id))

    sessions = []
    try:
        sessions = (TherapySession.query
                    .filter_by(professional_id=pro.id, patient_id=user.id)
                    .order_by(TherapySession.start_at.desc()).limit(10).all())
    except Exception:
        pass
    thread = _get_or_create_thread(pro.id, user.id)

    return render_or_text("pro/patient_dossier.html", "Dossier patient",
                          professional=pro, patient=user, case=case, profile=profile,
                          medhist=medhist, sessions=sessions, thread=thread)

# ====== Exercices (côté PRO : créer/éditer/téléverser + envoyer) =============
@app.route("/pro/patients/<int:patient_id>/exercises", methods=["GET","POST"], endpoint="pro_patient_exercises")
@login_required
def pro_patient_exercises(patient_id: int):
    pro = _current_professional_or_403()
    user = User.query.get_or_404(patient_id)
    if user.user_type != "patient": abort(404)
    _ensure_patient_case(pro.id, user.id)

    if request.method == "POST":
        f = request.form
        title = (f.get("title") or "").strip()
        text_content = (f.get("text_content") or "").strip() or None
        fmt = (f.get("content_format") or "texte").strip().lower()
        visibility = (f.get("visibility") or "my_patients").strip()
        due_date = f.get("due_date")
        technique = (f.get("technique") or "").strip() or None
        family = (f.get("family") or "").strip() or None

        # Nouveau ou existant
        if title:
            ex = Exercise(
                owner_id=current_user.id, professional_id=pro.id,
                title=title, description=(f.get("description") or None),
                family=family, type=(f.get("type") or "exercice"), technique=technique,
                content_format=fmt, text_content=text_content, visibility=visibility, is_approved=False
            )
            up = request.files.get("file")
            if up and getattr(up, "filename", ""):
                try:
                    name = _save_attachment(up); ex.file_url = f"/u/attachments/{name}"
                except Exception:
                    flash("Fichier non accepté.", "warning")
            db.session.add(ex); db.session.commit()
        else:
            ex_id = f.get("exercise_id", type=int)
            if not ex_id:
                flash("Indiquez un titre OU choisissez un exercice existant.", "warning")
                return redirect(url_for("pro_patient_exercises", patient_id=user.id))
            ex = Exercise.query.get_or_404(ex_id)

        _assign_exercise_to_patient(ex, pro.id, user.id, due_date)
        thread = _get_or_create_thread(pro.id, user.id)
        _notify_in_thread(thread, current_user.id, f"Un exercice vous a été assigné : {ex.title}.")
        _email_or_pass(getattr(user, "email", None),
                       f"{BRAND_NAME} — Nouvel exercice",
                       f"Un nouvel exercice « {ex.title} » est disponible dans votre espace patient.")
        flash("Exercice envoyé au patient.", "success")
        return redirect(url_for("pro_patient_exercises", patient_id=user.id))

    assigns = []
    try:
        q = ExerciseAssignment.query.filter(ExerciseAssignment.professional_id == pro.id)
        if hasattr(ExerciseAssignment, "patient_user_id"):
            q = q.filter(ExerciseAssignment.patient_user_id == user.id)
        else:
            q = q.filter(ExerciseAssignment.patient_id == user.id)
        assigns = q.order_by(ExerciseAssignment.created_at.desc().nullslast()).all()
    except Exception:
        pass

    existing = []
    try:
        existing = (Exercise.query
                    .filter(or_(Exercise.visibility.in_(("public","my_patients")),
                                Exercise.owner_id == current_user.id,
                                Exercise.professional_id == pro.id))
                    .order_by(Exercise.created_at.desc())
                    .limit(50).all())
    except Exception:
        pass

    return render_or_text("pro/patient_exercises.html", "Exercices du patient",
                          professional=pro, patient=user, assignments=assigns, library=existing)

# ====== Côté patient : liste ================================================
@app.route("/patient/exercises", methods=["GET"], endpoint="patient_exercises")
@login_required
def patient_exercises():
    if getattr(current_user, "user_type", None) != "patient": abort(403)
    q = ExerciseAssignment.query
    if hasattr(ExerciseAssignment, "patient_user_id"):
        q = q.filter_by(patient_user_id=current_user.id)
    else:
        q = q.filter_by(patient_id=current_user.id)
    assigns = (q.order_by(ExerciseAssignment.created_at.desc().nullslast()).all()
               if hasattr(ExerciseAssignment, "created_at") else q.all())
    return render_or_text("patient/exercises.html", "Mes exercices", assignments=assigns)

# ====== Côté patient : détail + remise ======================================
@app.route("/patient/exercises/<int:assign_id>", methods=["GET","POST"], endpoint="patient_exercise_detail")
@login_required
def patient_exercise_detail(assign_id: int):
    if getattr(current_user, "user_type", None) != "patient": abort(403)
    a = ExerciseAssignment.query.get_or_404(assign_id)
    ok = (a.patient_user_id == current_user.id) if hasattr(a, "patient_user_id") else (a.patient_id == current_user.id)
    if not ok: abort(403)
    ex = getattr(a, "exercise", None) or (Exercise.query.get(a.exercise_id) if hasattr(a, "exercise_id") else None)
    pro = Professional.query.get(a.professional_id)

    if request.method == "POST":
        f = request.form
        text_answer = (f.get("text_answer") or "").strip() or None
        upload = request.files.get("file_answer")
        file_url = None
        if upload and getattr(upload, "filename", ""):
            try:
                name = _save_attachment(upload); file_url = f"/u/attachments/{name}"
                try:
                    pf = PatientFile(
                        user_id=current_user.id, professional_id=a.professional_id,
                        file_url=file_url, file_name=upload.filename, content_type=upload.mimetype,
                        size_bytes=getattr(upload, "content_length", 0) or 0,
                    )
                    db.session.add(pf)
                except Exception: pass
            except Exception:
                flash("Fichier non accepté.", "warning")
        try:
            if "ExerciseProgress" in globals():
                ep = ExerciseProgress(
                    exercise_id=getattr(ex, "id", None),
                    assignment_id=getattr(a, "id", None) if hasattr(a, "id") else None,
                    patient_user_id=current_user.id if hasattr(ExerciseProgress, "patient_user_id") else None,
                    status="submitted", notes=text_answer or None
                )
                if file_url and hasattr(ep, "file_url"): ep.file_url = file_url
                db.session.add(ep)
        except Exception:
            pass
        thread = _get_or_create_thread(a.professional_id, current_user.id)
        body = f"Le patient a rendu l'exercice : {getattr(ex,'title','Exercice')}."
        if text_answer: body += f"\n\nRéponse :\n{text_answer[:2000]}"
        _notify_in_thread(thread, current_user.id, body, file_url)
        _email_or_pass(getattr(pro, "email", None),
                       f"{BRAND_NAME} — Réponse d'exercice",
                       f"Votre patient a rendu l'exercice « {getattr(ex,'title','Exercice')} ».")        
        try:
            db.session.commit(); flash("Réponse envoyée au professionnel.", "success")
        except Exception:
            db.session.rollback(); flash("Impossible d'enregistrer la réponse.", "danger")
        return redirect(url_for("patient_exercise_detail", assign_id=a.id))

    return render_or_text("patient/exercise_detail.html", "Exercice",
                          assignment=a, exercise=ex, professional=pro)

# =========================
#   ESPACE PATIENT (CLEAN)
# =========================

def _require_patient():
    if not current_user.is_authenticated or current_user.user_type != "patient":
        abort(403)

# ---------- Accueil ----------
@app.route("/patient", endpoint="patient_home")
@login_required
def patient_home():
    _require_patient()

    # Import local sûr
    from datetime import datetime, time as _Time

    # 0) Initialisations pour éviter toute NameError (contrat fixe : jamais casser le rendu)
    next_appointment = None
    pending_requests = []
    exercises = []
    docs_count = 0
    invoices_due = 0
    last_message = None

    # --- Profils & blocs existants (inchangés) ---
    profile = PatientProfile.query.filter_by(user_id=current_user.id).first()
    my_threads = (MessageThread.query
                  .filter_by(patient_id=current_user.id)
                  .order_by(MessageThread.updated_at.desc().nullslast())
                  .all())
    my_assignments = (ExerciseAssignment.query
                      .filter_by(patient_id=current_user.id)
                      .order_by(ExerciseAssignment.created_at.desc())
                      .limit(10).all())
    my_sessions = (TherapySession.query
                   .filter_by(patient_id=current_user.id)
                   .order_by(TherapySession.start_at.desc())
                   .limit(10).all())

    # =========================
    #   RDV : helpers robustes
    # =========================
    # Champ datetime connu en DB
    dt_field = None
    if hasattr(Appointment, "appointment_date"):
        dt_field = Appointment.appointment_date
    elif hasattr(Appointment, "start_at"):
        dt_field = Appointment.start_at

    # Statuts (on couvre les variantes courantes)
    PENDING = {"requested", "pending", "en_attente"}
    CANCELLED = {"cancelled", "canceled", "refused", "rejected", "declined", "annule", "annulé", "no_show"}
    CONFIRMED_HINTS = {"confirmed", "accepted", "approved", "valide", "validated"}

    def _extract_dt(a):
        """Retourne un datetime à partir de plusieurs schémas possibles."""
        # 1) Datetime direct
        for attr in ("appointment_date", "start_at", "scheduled_at", "start_time_dt"):
            v = getattr(a, attr, None)
            if isinstance(v, datetime):
                return v
        # 2) Date + time séparés
        d = getattr(a, "date", None) or getattr(a, "appointment_day", None)
        t = getattr(a, "time", None) or getattr(a, "appointment_time", None) or getattr(a, "start_time", None)
        if d and t:
            try:
                if isinstance(t, str) and ":" in t:
                    hh, mm = t.split(":")[:2]
                    t = _Time(int(hh), int(mm))
                return datetime.combine(d, t)
            except Exception:
                pass
        # 3) Date seule → midi par défaut
        if d:
            try:
                return datetime.combine(d, _Time(12, 0))
            except Exception:
                pass
        return None

    def _is_confirmed(a):
        """Considère le RDV confirmé s'il n'est ni pending ni cancelled (ou explicitement confirmé)."""
        st = getattr(a, "status", None)
        if st is None:
            return True  # pas de champ status → on traite comme confirmé
        st_l = str(st).strip().lower()
        if st_l in CANCELLED:
            return False
        if st_l in PENDING:
            return False
        if st_l in CONFIRMED_HINTS:
            return True
        return True  # autres statuts inconnus → on les considère confirmés

    now = datetime.utcnow()

    # -------------------------
    #   Demandes en attente
    # -------------------------
    try:
        base = Appointment.query.filter(Appointment.patient_id == current_user.id)
        if hasattr(Appointment, "status"):
            base = base.filter(Appointment.status.in_(list(PENDING)))
        # Ordonner par date si disponible, sinon par id
        if dt_field is not None:
            base = base.order_by(dt_field.asc())
        else:
            base = base.order_by(Appointment.id.desc())

        rows = base.limit(10).all()
        tmp = []
        for r in rows:
            when_dt = _extract_dt(r)
            pro_name = None
            try:
                if getattr(r, "professional", None) and getattr(r.professional, "name", None):
                    pro_name = r.professional.name
                elif getattr(r, "professional_id", None):
                    pro = Professional.query.get(r.professional_id)
                    pro_name = getattr(pro, "name", None)
            except Exception:
                pass
            tmp.append({
                "pro": pro_name or "—",
                "date": when_dt.strftime("%d/%m/%Y %H:%M") if isinstance(when_dt, datetime) else "—",
                "status": getattr(r, "status", "en attente")
            })
        pending_requests = tmp
    except Exception:
        pending_requests = []

    # -------------------------
    #   Prochain RDV confirmé à venir
    # -------------------------
    try:
        q = Appointment.query.filter(Appointment.patient_id == current_user.id)
        if dt_field is not None:
            q = q.filter(dt_field >= now).order_by(dt_field.asc())
        else:
            q = q.order_by(Appointment.id.desc())  # pas de champ datetime → on trie par id

        candidates = q.limit(100).all()
        best, best_dt = None, None
        for a in candidates:
            dtv = _extract_dt(a)
            if not dtv or dtv < now:
                continue
            if not _is_confirmed(a):
                continue
            if (best_dt is None) or (dtv < best_dt):
                best, best_dt = a, dtv

        if best and best_dt:
            where = getattr(best, "location", None) or getattr(best, "place", None) or getattr(best, "address", None)
            link = getattr(best, "meeting_link", None) or getattr(best, "video_link", None) or None
            pro_obj = getattr(best, "professional", None)
            if pro_obj is None and getattr(best, "professional_id", None):
                try:
                    pro_obj = Professional.query.get(best.professional_id)
                except Exception:
                    pro_obj = None

            next_appointment = {
                "when": best_dt.strftime("%d/%m/%Y à %H:%M"),
                "where": where,
                "link": link,
                "professional": pro_obj
            }
        else:
            next_appointment = None
    except Exception:
        next_appointment = None

    # -------------------------
    #   Mes exercices (mapping simple)
    # -------------------------
    try:
        for a in my_assignments:
            ex = getattr(a, "exercise", None)
            title = getattr(ex, "title", None) or getattr(ex, "name", None) or "Exercice"
            due = getattr(a, "due_date", None)
            exercises.append({
                "title": title,
                "due": due.strftime("%d/%m/%Y") if due else None,
                "status": getattr(a, "status", None) or "assigné"
            })
    except Exception:
        exercises = []

    # -------------------------
    #   Documents & Factures
    # -------------------------
    try:
        if "FileAttachment" in globals():
            docs_count = FileAttachment.query.filter_by(patient_id=current_user.id).count()
    except Exception:
        docs_count = 0

    try:
        if "Invoice" in globals():
            q = Invoice.query.filter_by(patient_id=current_user.id)
            if hasattr(Invoice, "status"):
                q = q.filter(Invoice.status.in_(["due", "unpaid"]))
            invoices_due = q.count()
    except Exception:
        invoices_due = 0

    # -------------------------
    #   Dernier message
    # -------------------------
    try:
        last = (Message.query
                .join(MessageThread, Message.thread_id == MessageThread.id)
                .filter(MessageThread.patient_id == current_user.id)
                .order_by(Message.created_at.desc())
                .first())
        if last:
            pro_name = None
            try:
                th = MessageThread.query.get(last.thread_id)
                if th and getattr(th, "professional_id", None):
                    pro = Professional.query.get(th.professional_id)
                    pro_name = getattr(pro, "name", None)
            except Exception:
                pass
            last_message = {
                "with": pro_name or "—",
                "at": getattr(last, "created_at", None).strftime("%d/%m/%Y %H:%M") if getattr(last, "created_at", None) else "",
                "excerpt": (last.body[:120] + "…") if getattr(last, "body", None) and len(last.body) > 120 else (last.body or "")
            }
    except Exception:
        last_message = None

    # Rendu : on injecte les clés attendues par le template home.html
    return render_or_text(
        "patient/home.html", "Espace patient",
        profile=profile,
        threads=my_threads,
        assignments=my_assignments,
        sessions=my_sessions,
        next_appointment=next_appointment,
        pending_requests=pending_requests,
        exercises=exercises,
        docs_count=docs_count,
        invoices_due=invoices_due,
        last_message=last_message
    )


# ---------- Rendez-vous ----------
if "patient_appointments" not in app.view_functions:
    @app.route("/patient/appointments", methods=["GET"], endpoint="patient_appointments")
    @login_required
    def patient_appointments():
        _require_patient()
        appts = (Appointment.query
                 .filter_by(patient_id=current_user.id)
                 .order_by(Appointment.appointment_date.desc())
                 .all())
        return render_or_text("patient/appointments.html", "Mes rendez-vous", appointments=appts)

# ---------- Rendez-vous : alias simple vers la réservation ----------
@app.route("/patient/book/<int:professional_id>", methods=["GET"], endpoint="patient_book")
@login_required
def patient_book(professional_id):
    _require_patient()
    return redirect(url_for("patient_availability", professional_id=professional_id))
# ==== FILTRES PROFESSIONNELS (SANS TABS) ====
from sqlalchemy import or_
from datetime import datetime

def _build_professional_query_from_args(args):
    qs = Professional.query

    # 1) Pré-filtrage par ID si transmis
    prof_id = args.get("professional_id", type=int)
    if prof_id:
        qs = qs.filter(Professional.id == prof_id)

    # 2) Statut/activité : désactivé pour éviter "0 résultat" si valeurs DB inconnues
    # if hasattr(Professional, "status"):
    #     qs = qs.filter(Professional.status == 'valide')
    # elif hasattr(Professional, "is_active"):
    #     qs = qs.filter(Professional.is_active.is_(True))

    # 3) Recherche plein texte simple
    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        conds = []
        for attr in ("name", "full_name", "description", "specialty", "location", "address"):
            if hasattr(Professional, attr):
                conds.append(getattr(Professional, attr).ilike(like))
        if conds:
            qs = qs.filter(or_(*conds))

    # 4) Ville
    city_id = args.get("city_id", type=int)
    if city_id and hasattr(Professional, "city_id"):
        qs = qs.filter(Professional.city_id == city_id)
    else:
        city = (args.get("city") or "").strip()
        if city and hasattr(Professional, "location"):
            qs = qs.filter(Professional.location.ilike(f"%{city}%"))

    # 5) Famille (catégorie)
    family = (args.get("family") or "").strip()
    if family:
        try:
            qs = qs.filter(
                or_(
                    Professional.primary_specialty.has(Specialty.category.ilike(family)),
                    Professional.specialties.any(Specialty.category.ilike(family)),
                    Professional.specialty.ilike(f"%{family}%"),
                )
            )
        except Exception:
            pass

    # 6) Spécialité
    specialty_id = args.get("specialty_id", type=int)
    if specialty_id:
        if hasattr(Professional, "primary_specialty_id"):
            qs = qs.filter(Professional.primary_specialty_id == specialty_id)
        try:
            if hasattr(Professional, "specialties"):
                qs = qs.filter(Professional.specialties.any(Specialty.id == specialty_id))
        except Exception:
            pass
    else:
        specialty = (args.get("specialty") or "").strip()
        if specialty and hasattr(Professional, "specialty"):
            qs = qs.filter(Professional.specialty.ilike(f"%{specialty}%"))

    # 7) Mode (présentiel / en_ligne / visio)
    mode = (args.get("mode") or "").strip().lower()
    if mode == "visio":
        mode = "en_ligne"
    if mode and hasattr(Professional, "consultation_types"):
        qs = qs.filter(Professional.consultation_types.ilike(f"%{mode}%"))

    # 8) Tri
    if hasattr(Professional, "is_featured"):
        qs = qs.order_by(Professional.is_featured.desc(), Professional.created_at.desc())
    elif hasattr(Professional, "created_at"):
        qs = qs.order_by(Professional.created_at.desc())
    else:
        qs = qs.order_by(Professional.id.desc())

    return qs

# ---------- Prendre RDV (formulaire) ----------
@app.route("/patient/booking", methods=["GET"], endpoint="patient_booking")
@login_required
def patient_booking():
    _require_patient()

    # Sélections filtres
    try:
        cities = City.query.order_by(City.name).all()
    except Exception:
        cities = []
    try:
        families = Family.query.order_by(Family.name).all()
    except Exception:
        families = []
    try:
        specialties = Specialty.query.order_by(Specialty.name).all()
    except Exception:
        specialties = []

    # Pros listés (construction depuis l'URL)
    try:
        qs = _build_professional_query_from_args(request.args)
    except Exception:
        qs = Professional.query

    # (sécurité) appliquer professional_id si présent même en cas d'exception au-dessus
    prof_id = request.args.get("professional_id", type=int)
    if prof_id:
        qs = qs.filter(Professional.id == prof_id)

    try:
        pros = qs.limit(12).all()
    except Exception:
        pros = []

    # Fallback si rien
    fallback = False
    if not pros:
        try:
            base = Professional.query
            pros = (base.order_by(Professional.created_at.desc()).limit(12).all()
                    if hasattr(Professional, "created_at")
                    else base.order_by(Professional.id.desc()).limit(12).all())
            fallback = True
        except Exception:
            pros = []

    first_pro = pros[0] if pros else type("X", (), {"id": 0})()

    return render_or_text(
        "patient/booking.html",
        "Prendre un rendez-vous",
        cities=cities, families=families, specialties=specialties,
        pros=pros, professionals=pros, pro=first_pro,
        fallback=fallback
    )

# ---------- Résultats pros (unique) ----------
if "patient_resources" not in app.view_functions:
    @app.route("/patient/resources", methods=["GET"], endpoint="patient_resources")
    @login_required
    def patient_resources():
        _require_patient()
        try:
            qs = _build_professional_query_from_args(request.args)
            professionals = qs.limit(100).all()
        except Exception:
            professionals = []

        fallback = False
        if not professionals:
            try:
                base = Professional.query
                professionals = (base.order_by(Professional.created_at.desc()).limit(24).all()
                                 if hasattr(Professional, "created_at")
                                 else base.order_by(Professional.id.desc()).limit(24).all())
                fallback = True
            except Exception:
                professionals = []

        # Listes UI (robustes)
        try:
            cities = _ui_cities()
        except Exception:
            try:
                cities = City.query.order_by(City.name).all()
            except Exception:
                cities = []
        try:
            specialties = _ui_specialties()
        except Exception:
            try:
                specialties = Specialty.query.order_by(Specialty.name).all()
            except Exception:
                specialties = []
        try:
            families = _ui_families_rows()
        except Exception:
            try:
                families = Family.query.order_by(Family.name).all()
            except Exception:
                families = []

        first_pro = professionals[0] if professionals else type("X", (), {"id": 0})()

        return render_or_text(
            "patient/resources.html", "Ressources",
            professionals=professionals, pros=professionals, pro=first_pro,
            cities=cities, families=families, specialties=specialties,
            fallback=fallback
        )

# ---------- API JSON (optionnelle) ----------
@app.route("/api/patient/resources", methods=["GET"], endpoint="patient_resources_api")
@login_required
def patient_resources_api():
    _require_patient()
    qs = _build_professional_query_from_args(request.args).limit(50).all()
    payload = []
    for p in qs:
        payload.append({
            "id": p.id,
            "name": getattr(p, "name", None),
            "specialty": (
                getattr(p, "specialty", None)
                or (getattr(p, "primary_specialty", None).name
                    if getattr(p, "primary_specialty", None) else None)
            ),
            "city": getattr(p, "city", None).name if hasattr(getattr(p, "city", None), "name") else getattr(p, "city", None),
            "profile_url": url_for("professional_detail", professional_id=p.id),
        })
    return jsonify(payload)

# ---------- Ressources/exercices ----------
# ====== Côté patient : liste ================================================
def _patient_exercises_view():
    if getattr(current_user, "user_type", None) != "patient":
        abort(403)
    q = ExerciseAssignment.query
    if hasattr(ExerciseAssignment, "patient_user_id"):
        q = q.filter_by(patient_user_id=current_user.id)
    else:
        q = q.filter_by(patient_id=current_user.id)
    assigns = (q.order_by(ExerciseAssignment.created_at.desc().nullslast()).all()
               if hasattr(ExerciseAssignment, "created_at") else q.all())
    return render_or_text("patient/exercises.html", "Mes exercices", assignments=assigns)

# ✅ N’enregistre la route que si l’endpoint n’existe pas déjà
if "patient_exercises" not in app.view_functions:
    app.add_url_rule(
        "/patient/exercises",
        endpoint="patient_exercises",
        view_func=login_required(_patient_exercises_view),
        methods=["GET"]
    )

# ====== Côté patient : détail + remise ======================================
def _patient_exercise_detail_view(assign_id: int):
    if getattr(current_user, "user_type", None) != "patient":
        abort(403)
    a = ExerciseAssignment.query.get_or_404(assign_id)
    ok = (a.patient_user_id == current_user.id) if hasattr(a, "patient_user_id") else (a.patient_id == current_user.id)
    if not ok:
        abort(403)
    ex = getattr(a, "exercise", None) or (Exercise.query.get(a.exercise_id) if hasattr(a, "exercise_id") else None)
    pro = Professional.query.get(a.professional_id)

    if request.method == "POST":
        f = request.form
        text_answer = (f.get("text_answer") or "").strip() or None
        upload = request.files.get("file_answer")
        file_url = None
        if upload and getattr(upload, "filename", ""):
            try:
                name = _save_attachment(upload); file_url = f"/u/attachments/{name}"
                try:
                    pf = PatientFile(
                        user_id=current_user.id, professional_id=a.professional_id,
                        file_url=file_url, file_name=upload.filename, content_type=upload.mimetype,
                        size_bytes=getattr(upload, "content_length", 0) or 0,
                    )
                    db.session.add(pf)
                except Exception:
                    pass
            except Exception:
                flash("Fichier non accepté.", "warning")
        try:
            if "ExerciseProgress" in globals():
                ep = ExerciseProgress(
                    exercise_id=getattr(ex, "id", None),
                    assignment_id=getattr(a, "id", None) if hasattr(a, "id") else None,
                    patient_user_id=current_user.id if hasattr(ExerciseProgress, "patient_user_id") else None,
                    status="submitted", notes=text_answer or None
                )
                if file_url and hasattr(ep, "file_url"):
                    ep.file_url = file_url
                db.session.add(ep)
        except Exception:
            pass
        thread = _get_or_create_thread(a.professional_id, current_user.id)
        body = f"Le patient a rendu l'exercice : {getattr(ex,'title','Exercice')}."
        if text_answer:
            body += f"\n\nRéponse :\n{text_answer[:2000]}"
        _notify_in_thread(thread, current_user.id, body, file_url)
        _email_or_pass(getattr(pro, "email", None),
                       f"{BRAND_NAME} — Réponse d'exercice",
                       f"Votre patient a rendu l'exercice « {getattr(ex,'title','Exercice')} ».")        
        try:
            db.session.commit(); flash("Réponse envoyée au professionnel.", "success")
        except Exception:
            db.session.rollback(); flash("Impossible d'enregistrer la réponse.", "danger")
        return redirect(url_for("patient_exercise_detail", assign_id=a.id))

    return render_or_text("patient/exercise_detail.html", "Exercice",
                          assignment=a, exercise=ex, professional=pro)

# ✅ Même logique : n’enregistre que si l’endpoint n’existe pas encore
if "patient_exercise_detail" not in app.view_functions:
    app.add_url_rule(
        "/patient/exercises/<int:assign_id>",
        endpoint="patient_exercise_detail",
        view_func=login_required(_patient_exercise_detail_view),
        methods=["GET", "POST"]
    )


# ---------- Carnet thérapeutique ----------
@app.route("/patient/notebook", methods=["GET", "POST"], endpoint="patient_notebook")
@login_required
def patient_notebook():
    _require_patient()
    if request.method == "POST":
        pro_id = request.form.get("professional_id", type=int)
        entry_type = (request.form.get("entry_type") or "note").strip()
        title = (request.form.get("title") or "").strip() or None
        content = (request.form.get("content") or "").strip()
        entry = TherapyNotebookEntry(
            patient_id=current_user.id, professional_id=pro_id or 0, author_id=current_user.id,
            entry_type=entry_type, title=title, content=content
        )
        db.session.add(entry)
        db.session.commit()
        flash("Entrée ajoutée au carnet.", "success")
        return redirect(url_for("patient_notebook"))

    entries = (TherapyNotebookEntry.query
               .filter_by(patient_id=current_user.id)
               .order_by(TherapyNotebookEntry.created_at.desc()).all())
    return render_or_text("patient/notebook.html", "Carnet thérapeutique", entries=entries)

# ---------- Journal personnel ----------
@app.route("/patient/journal", methods=["GET", "POST"], endpoint="patient_journal")
@login_required
def patient_journal():
    _require_patient()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip() or None
        content = (request.form.get("content") or "").strip()
        emotion = (request.form.get("emotion") or "").strip() or None
        share = request.form.get("share") == "on"
        e = PersonalJournalEntry(
            patient_id=current_user.id, title=title, content=content, emotion=emotion,
            is_shared_with_pro=share
        )
        db.session.add(e)
        db.session.commit()
        flash("Journal enregistré.", "success")
        return redirect(url_for("patient_journal"))

    entries = (PersonalJournalEntry.query
               .filter_by(patient_id=current_user.id)
               .order_by(PersonalJournalEntry.created_at.desc()).all())
    return render_or_text("patient/journal.html", "Journal personnel", entries=entries)

# ---------- Avis ----------
@app.route("/patient/ratings", methods=["GET", "POST"], endpoint="patient_ratings")
@login_required
def patient_ratings():
    _require_patient()
    if request.method == "POST":
        professional_id = request.form.get("professional_id", type=int)
        rating = request.form.get("rating", type=int)
        comment = (request.form.get("comment") or "").strip() or None
        r = ProfessionalReview(
            patient_id=current_user.id, professional_id=professional_id,
            rating=rating, comment=comment, is_public=True
        )
        db.session.add(r)
        db.session.commit()
        flash("Avis publié.", "success")
        return redirect(url_for("patient_ratings"))

    my_reviews = (ProfessionalReview.query
                  .filter_by(patient_id=current_user.id)
                  .order_by(ProfessionalReview.created_at.desc()).all())
    return render_or_text("patient/ratings.html", "Mes avis", reviews=my_reviews)

# ---------- Charte & confidentialité ----------
@app.route("/patient/charter", methods=["GET", "POST"], endpoint="patient_charter")
@login_required
def patient_charter():
    _require_patient()
    if request.method == "POST":
        policy_key = (request.form.get("policy_key") or "ethic_charter").strip()
        version = (request.form.get("version") or "v1").strip()
        db.session.add(ConsentLog(
            user_id=current_user.id, policy_key=policy_key, version=version, accepted_at=datetime.utcnow()
        ))
        db.session.commit()
        flash("Consentement enregistré.", "success")
        return redirect(url_for("patient_charter"))

    logs = (ConsentLog.query
            .filter_by(user_id=current_user.id)
            .order_by(ConsentLog.accepted_at.desc()).all())
    return render_or_text("patient/charter.html", "Charte & confidentialité", consents=logs)

# ---------- Messagerie avec un pro ----------
@app.route("/patient/thread/<int:professional_id>", methods=["GET", "POST"], endpoint="patient_thread")
@login_required
def patient_thread(professional_id: int):
    _require_patient()
    pro = Professional.query.get_or_404(professional_id)
    thread = MessageThread.query.filter_by(patient_id=current_user.id, professional_id=pro.id).first()
    if not thread:
        thread = MessageThread(patient_id=current_user.id, professional_id=pro.id, is_anonymous=False)
        db.session.add(thread)
        db.session.commit()

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        file = request.files.get("attachment")
        audio = request.files.get("audio")
        attachment = None

        if file:
            try:
                name = _save_attachment(file)
                attachment = FileAttachment(
                    file_url=f"/u/attachments/{name}",
                    file_name=file.filename,
                    content_type=file.mimetype,
                    size_bytes=file.content_length or 0,
                    owner_user_id=current_user.id,
                    patient_id=current_user.id
                )
                db.session.add(attachment)
                db.session.flush()
            except Exception:
                flash("Pièce jointe non acceptée.", "warning")

        audio_url = None
        if audio:
            try:
                name = _save_attachment(audio)
                audio_url = f"/u/attachments/{name}"
            except Exception:
                flash("Audio non accepté.", "warning")

        msg = Message(
            thread_id=thread.id, sender_id=current_user.id, body=body or None,
            attachment_id=attachment.id if attachment else None, audio_url=audio_url
        )
        db.session.add(msg)
        db.session.commit()

        try:
            pro_user = User.query.filter_by(username=pro.name).first()
            if pro_user and pro_user.email:
                safe_send_email(
                    pro_user.email,
                    f"{BRAND_NAME} — Nouveau message patient",
                    f"Un patient vous a écrit sur {BRAND_NAME}."
                )
        except Exception:
            pass

        return redirect(url_for("patient_thread", professional_id=pro.id))

    messages = (Message.query
                .filter_by(thread_id=thread.id)
                .order_by(Message.created_at.asc()).all())
    return render_or_text(
        "patient/thread.html", "Messagerie sécurisée",
        professional=pro, thread=thread, messages=messages
    )

# ---------- Alias public /book/<id> ----------
@app.route("/book/<int:professional_id>", methods=["GET"], endpoint="book_alias")
def book_alias(professional_id):
    next_url = url_for("patient_availability", professional_id=professional_id)
    if current_user.is_authenticated and getattr(current_user, "user_type", None) == "patient":
        return redirect(next_url)
    return redirect(url_for("login", next=next_url))

# ---------- Liste publique de pros ----------
if "professionals_public" not in app.view_functions:
    @app.get("/professionals", endpoint="professionals_public")
    def professionals_public():
        try:
            base = Professional.query
            pros = (base.order_by(Professional.created_at.desc()).limit(100).all()
                    if hasattr(Professional, "created_at")
                    else base.order_by(Professional.id.desc()).limit(100).all())
        except Exception:
            pros = []
        first_pro = pros[0] if pros else type("X", (), {"id": 0})()
        return render_or_text("patient/resources.html", "Ressources",
                              professionals=pros, pros=pros, pro=first_pro,
                              cities=[], families=[], specialties=[], fallback=False)


# ---------- Pages diverses (placeholders sûrs) ----------
@app.get("/patient/documents")
@login_required
def patient_documents():
    _require_patient()
    return render_or_text("patient/files.html", "Mes documents")

@app.get("/patient/billing")
@login_required
def patient_billing():
    _require_patient()
    return render_or_text("patient/billing.html", "Ma facturation")

@app.get("/patient/messages")
@login_required
def patient_messages():
    _require_patient()
    return render_or_text("patient/messages_inbox.html", "Messagerie")

@app.get("/patient/profile")
@login_required
def patient_profile():
    _require_patient()
    return render_or_text("patient/profile.html", "Mon profil")

@app.get("/patient/help")
@login_required
def patient_help():
    _require_patient()
    return render_or_text("patient/help.html", "Aide & support")

# =========================
#   STATUT / ERREURS
# =========================
@app.route("/site-status", endpoint="site_status")
def site_status():
    status = app.config.get("SITE_STATUS", {})
    stats = {
        "total_professionals": Professional.query.count(),
        "total_users": User.query.count(),
        "total_appointments": Appointment.query.count(),
    }
    return render_or_text("site_status.html", "Statut du site", status=status, stats=stats)

@app.errorhandler(404)
def not_found(e):
    return render_or_text("errors/404.html", "404 — Page non trouvée"), 404

@app.errorhandler(500)
def server_error(e):
    return render_or_text("errors/500.html", "500 — Erreur serveur"), 500

# --- Aliases pour compatibilité des templates existants ---
from werkzeug.routing import BuildError

@app.route("/pro/patients/list", methods=["GET"], endpoint="pro_list_patients")
@login_required
def pro_list_patients_alias():
    try:
        return pro_patients()
    except Exception:
        return redirect(url_for("pro_patients", **request.args))

# "Réserver un rendez-vous" attendu par professional_detail.html
@app.route("/book/<int:professional_id>", methods=["GET"], endpoint="book_appointment")
@login_required
def book_appointment(professional_id: int):
    if getattr(current_user, "user_type", None) != "patient":
        flash("Connectez-vous en tant que patient pour réserver un rendez-vous.", "warning")
    try:
        return redirect(url_for("professional_detail", professional_id=professional_id))
    except BuildError:
        return redirect(url_for("index"))
# ========= PATIENT BOOKING (en s'appuyant sur les plages "pro") =========
# =========================
#   DISPONIBILITÉS PATIENT
# =========================

def _get_availability_model():
    for name in (
        "ProfessionalDayWindow",
        "AvailabilityWindow",
        "ProfessionalAvailabilityWindow",
        "WorkingWindow",
        "AvailabilitySlotDefinition",
    ):
        if name in globals():
            return globals()[name]
    return None

def _weekly_windows_for(professional_id: int):
    Model = _get_availability_model()
    result = {i: [] for i in range(7)}
    if not Model:
        return result

    try:
        q = Model.query.filter(getattr(Model, "professional_id") == professional_id)
        rows = q.all()
        from datetime import time as _Time
        for r in rows:
            wd = int(getattr(r, "weekday"))
            s = getattr(r, "start_time")
            e = getattr(r, "end_time")
            def _to_time(v):
                if isinstance(v, _Time): return v
                if isinstance(v, str) and v:
                    hh, mm = v.split(":")[:2]
                    return _Time(int(hh), int(mm))
                return None
            ts, te = _to_time(s), _to_time(e)
            if ts and te and 0 <= wd <= 6:
                result[wd].append((ts, te))
        for k in result:
            result[k].sort(key=lambda t: (t[0].hour, t[0].minute))
    except Exception:
        pass
    return result

def _session_settings_for(pro):
    duration = 60
    buffer_m = 0
    try:
        profile = getattr(pro, "profile", None)
        if profile:
            duration = int(getattr(profile, "session_duration_minutes", duration) or duration)
            buffer_m = int(getattr(profile, "buffer_between_sessions_minutes", buffer_m) or buffer_m)
        duration = int(getattr(pro, "session_duration_minutes", duration) or duration)
        buffer_m = int(getattr(pro, "buffer_between_sessions_minutes", buffer_m) or buffer_m)
    except Exception:
        pass
    duration = max(15, min(duration, 180))
    buffer_m = max(0, min(buffer_m, 60))
    return duration, buffer_m

def _build_slots_from_weekly(pro, start_date: date, days: int):
    weekly = _weekly_windows_for(pro.id)
    duration, buffer_m = _session_settings_for(pro)
    step = duration + buffer_m
    slots = []
    for i in range(days):
        day = start_date + timedelta(days=i)
        wd = day.weekday()
        for (t1, t2) in weekly.get(wd, []):
            cur = datetime.combine(day, t1)
            end = datetime.combine(day, t2)
            while cur + timedelta(minutes=duration) <= end:
                slots.append(cur.replace(second=0, microsecond=0))
                cur += timedelta(minutes=step)
    if not slots:
        for i in range(days):
            day = start_date + timedelta(days=i)
            for h in range(9, 17):
                slots.append(datetime.combine(day, dtime(hour=h)).replace(second=0, microsecond=0))
    return slots

def _taken_keys_for(professional_id: int, start_date: date, days: int):
    start_dt = datetime.combine(start_date, dtime.min)
    end_dt   = datetime.combine(start_date + timedelta(days=days), dtime.min)
    taken = set()
    try:
        q = Appointment.query.filter(Appointment.professional_id == professional_id)
        dt_field = Appointment.appointment_date if hasattr(Appointment, "appointment_date") else getattr(Appointment, "start_at")
        q = q.filter(dt_field >= start_dt, dt_field < end_dt)
        if hasattr(Appointment, "status"):
            q = q.filter(Appointment.status.in_(["confirmed", "requested"]))
        for a in q.all():
            dt = getattr(a, "appointment_date", None) or getattr(a, "start_at", None)
            if isinstance(dt, datetime):
                taken.add(dt.replace(second=0, microsecond=0))
    except Exception:
        pass
    return taken

# -- 1) Page d’affichage des créneaux patient --------------------------------
@app.route("/patient/availability/<int:professional_id>", methods=["GET"], endpoint="patient_availability")
@login_required
def patient_availability(professional_id: int):
    _require_patient()
    pro = Professional.query.get_or_404(professional_id)
    days = int(request.args.get("days", 7))
    days = max(1, min(days, 30))
    start_date = datetime.utcnow().date()

    all_slots = _build_slots_from_weekly(pro, start_date, days)
    taken = _taken_keys_for(professional_id, start_date, days)

    grouped = {}
    for dt in all_slots:
        key = dt.replace(second=0, microsecond=0)
        d = key.strftime("%Y-%m-%d")
        grouped.setdefault(d, []).append({
            "iso": key.strftime("%Y-%m-%d %H:%M"),
            "time": key.strftime("%H:%M"),
            "free": key not in taken
        })

    return render_or_text(
        "patient/availability.html",
        "Choisir un créneau",
        professional=pro, grouped_slots=grouped, days=days
    )

@app.route("/patient/appointments/confirm", methods=["POST"], endpoint="patient_confirm_booking")
@login_required
def patient_confirm_booking():
    _require_patient()
    pro_id = request.form.get("professional_id", type=int)
    when   = (request.form.get("when") or "").strip()
    if not pro_id or not when:
        flash("Créneau invalide.", "warning")
        return redirect(url_for("patient_home"))

    pro = Professional.query.get_or_404(pro_id)
    appt_dt = None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            appt_dt = datetime.strptime(when, fmt)
            break
        except ValueError:
            continue
    if not appt_dt:
        flash("Format de date/heure non reconnu.", "warning")
        return redirect(url_for("patient_availability", professional_id=pro_id))

    try:
        q = Appointment.query.filter(Appointment.professional_id == pro_id)
        dt_field = Appointment.appointment_date if hasattr(Appointment, "appointment_date") else getattr(Appointment, "start_at")
        q = q.filter(dt_field == appt_dt)
        if hasattr(Appointment, "status"):
            q = q.filter(Appointment.status.in_(["confirmed", "requested"]))
        if q.first():
            flash("Ce créneau vient d’être pris, choisissez un autre créneau.", "warning")
            return redirect(url_for("patient_availability", professional_id=pro_id))
    except Exception:
        pass

    kwargs = dict(patient_id=current_user.id, professional_id=pro_id)
    if hasattr(Appointment, "appointment_date"):
        kwargs["appointment_date"] = appt_dt
    else:
        kwargs["start_at"] = appt_dt
    if hasattr(Appointment, "status"):
        kwargs["status"] = "requested"

    appt = Appointment(**kwargs)
    db.session.add(appt)
    db.session.commit()

    try:
        if 'Notification' in globals():
            db.session.add(Notification(
                user_id=getattr(pro, "user_id", None),
                title="Nouvelle demande de rendez-vous",
                body=f"Un patient demande {appt_dt.strftime('%Y-%m-%d %H:%M')}",
                kind="appointment_request"
            ))
            db.session.add(Notification(
                user_id=current_user.id,
                title="Demande envoyée",
                body="Votre demande de rendez-vous est en attente de validation.",
                kind="appointment_request"
            ))
            db.session.commit()
    except Exception:
        pass

    try:
        pro_user = User.query.filter_by(username=getattr(pro, "name", None)).first()
        if pro_user and pro_user.email:
            safe_send_email(
                pro_user.email,
                f"{BRAND_NAME} — Demande de RDV",
                f"Un patient a demandé un rendez-vous le {appt_dt.strftime('%Y-%m-%d %H:%M')}."
            )
    except Exception:
        pass
    try:
        if getattr(current_user, "email", None):
            safe_send_email(
                current_user.email,
                f"{BRAND_NAME} — Demande envoyée",
                "Votre demande de rendez-vous a été transmise au professionnel."
            )
    except Exception:
        pass

    flash("Demande envoyée. Vous serez notifié(e) après validation du professionnel.", "success")
    return redirect(url_for("patient_appointments"))


# =========================
#   BOOT (migrations légères + admin seed + TAXONOMIE)
# =========================
def _bootstrap_taxonomy():
    inserted_cities = 0
    inserted_specs = 0
    updated_categ = 0

    try:
        for obj in CITY_OBJECTS:
            name = (obj.get("name_fr") or obj.get("name") or "").strip()
            if not name:
                continue
            exists = City.query.filter(db.func.lower(City.name) == name.lower()).first()
            if not exists:
                db.session.add(City(name=name))
                inserted_cities += 1
    except Exception as e:
        current_app.logger.warning("Bootstrap villes: %s", e)

    try:
        for fam in SPECIALTY_FAMILIES:
            cat = (fam.get("name_fr") or "").strip()
            for sp in fam.get("specialties", []):
                sp_name = (sp.get("name_fr") or sp.get("name") or "").strip()
                if not sp_name:
                    continue
                row = Specialty.query.filter(db.func.lower(Specialty.name) == sp_name.lower()).first()
                if not row:
                    db.session.add(Specialty(name=sp_name, category=cat))
                    inserted_specs += 1
                else:
                    if not (row.category or "").strip():
                        row.category = cat
                        updated_categ += 1
    except Exception as e:
        current_app.logger.warning("Bootstrap spécialités: %s", e)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning("Bootstrap taxonomy commit: %s", e)

    current_app.logger.info(
        "Taxonomy seed → villes +%d, spécialités +%d, catégories complétées %d",
        inserted_cities, inserted_specs, updated_categ
    )

with app.app_context():
    db.create_all()
    try:
        stmts = [
            # --- professionals : colonnes additionnelles (idempotent)
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS address VARCHAR(255);",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS facebook_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS instagram_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS tiktok_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS youtube_url TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS social_links_approved BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER DEFAULT 45;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS buffer_between_appointments_minutes INTEGER DEFAULT 15;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS featured_rank INTEGER;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS certified_tighri BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS approved_anthecc BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS city_id INTEGER REFERENCES cities(id) ON DELETE SET NULL;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS primary_specialty_id INTEGER REFERENCES specialties(id) ON DELETE SET NULL;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url2 TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url3 TEXT;",

            # --- users : colonnes OAuth / reset / profil
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;",

            # --- patient_profiles : champs utilisés par l'app
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS first_name VARCHAR(120);",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS last_name VARCHAR(120);",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS birth_date DATE;",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS language VARCHAR(10);",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS preferred_contact VARCHAR(30);",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS notes_public TEXT;",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS emergency_contact VARCHAR(255);",
            "ALTER TABLE patient_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();",

            # --- therapy_sessions : champs normalisés
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS start_at TIMESTAMP;",
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS end_at TIMESTAMP;",
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'planifie';",
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS mode VARCHAR(20) DEFAULT 'cabinet';",
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS meet_url TEXT;",
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS appointment_id INTEGER REFERENCES appointments(id) ON DELETE SET NULL;",

            # --- message_threads
            "ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS patient_id INTEGER REFERENCES users(id) ON DELETE CASCADE;",
            "ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS professional_id INTEGER REFERENCES professionals(id) ON DELETE CASCADE;",
            "ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();",
            "ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP;",
            "CREATE INDEX IF NOT EXISTS ix_threads_pro ON message_threads(professional_id);",
            "CREATE INDEX IF NOT EXISTS ix_threads_patient ON message_threads(patient_id);",

            # Compat rétro
            "ALTER TABLE therapy_sessions ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;",
            "UPDATE therapy_sessions SET started_at = start_at WHERE started_at IS NULL AND start_at IS NOT NULL;",

            # --- medical_histories
            "ALTER TABLE medical_histories ADD COLUMN IF NOT EXISTS summary TEXT;",
            "ALTER TABLE medical_histories ADD COLUMN IF NOT EXISTS custom_fields TEXT;",
        ]

        for sql in stmts:
            db.session.execute(text(sql))

        db.session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_ts_start  ON therapy_sessions (start_at);"))
        db.session.execute(text("CREATE INDEX IF NOT EXISTS ix_ts_status ON therapy_sessions (status);"))

        try:
            db.session.execute(text("UPDATE professionals SET consultation_fee = 0 WHERE consultation_fee IS NULL;"))
            db.session.execute(text("ALTER TABLE professionals ALTER COLUMN consultation_fee SET DEFAULT 0;"))
        except Exception as e:
            current_app.logger.warning(f"consultation_fee default/normalize: {e}")

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning(f"Mini-migration colonnes: {e}")

    # --- Taxonomy étendue
    try:
        _bootstrap_taxonomy()
    except Exception as e:
        app.logger.warning("Bootstrap taxonomy failed, fallback minimal: %s", e)
        if Specialty.query.count() == 0:
            for name in SEED_SPECIALTIES:
                try:
                    db.session.add(Specialty(name=name))
                except Exception:
                    pass
            db.session.commit()
        if City.query.count() == 0:
            for name in SEED_CITIES:
                try:
                    db.session.add(City(name=name))
                except Exception:
                    pass
            db.session.commit()

    # --- Admin par défaut
    admin_username = os.environ.get("ADMIN_USERNAME", "admin")
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@tighri.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
    admin_phone = os.environ.get("ADMIN_PHONE", "0663400190")
    u = User.query.filter_by(username=admin_username).first()
    if not u:
        u = User(
            username=admin_username,
            email=admin_email,
            password_hash=generate_password_hash(admin_password),
            is_admin=True,
            user_type="professional",
            phone=admin_phone
        )
        db.session.add(u); db.session.commit()
        app.logger.info("Admin '%s' créé.", admin_username)

# Pas de __main__: Gunicorn lance app:app

