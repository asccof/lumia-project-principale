# app.py — version unifiée et propre pour Tighri (Option B: 3 URL d’images)

from __future__ import annotations
import os, io, uuid, secrets, hashlib, requests
from datetime import datetime, date, timedelta, time as dtime
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from typing import Optional
from functools import lru_cache

from flask import (
    Flask, render_template, request, redirect, url_for, flash, jsonify,
    send_from_directory, Response, current_app, make_response, g, abort
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

from flask_login import (
    LoginManager, login_user, login_required, logout_user, current_user
)
from authlib.integrations.flask_client import OAuth
from sqlalchemy import or_, text

# ========== PIL (images) ==========
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

# ========== Notifications sûres ==========
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

# ========== Constantes ==========
BASE_DIR = Path(__file__).resolve().parent
BRAND_NAME = os.getenv("BRAND_NAME", "Tighri")

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", BASE_DIR / "uploads"))
UPLOAD_FOLDER = UPLOAD_ROOT / "profiles"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif"}
MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(5 * 1024 * 1024)))  # 5 Mo

DEFAULT_LANG = os.getenv("DEFAULT_LANG", "fr")
SUPPORTED_LANGS = {"fr", "ar", "en"}
LANG_COOKIE = "lang"

# ========== App ==========
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
app.config["REMEMBER_COOKIE_NAME"] = "tighri_remember"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=60)
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config['PREFERRED_URL_SCHEME'] = 'https'
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_CONTENT_LENGTH)

# Créer dossiers d’upload si besoin
try:
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
except Exception as e:
    app.logger.warning("Impossible de créer le dossier d'upload: %s", e)

# ========== DB & modèles ==========
def _normalize_pg_uri(uri: str) -> str:
    if not uri:
        return uri
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    if uri.startswith("postgresql+psycopg2://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)
    if parsed.scheme.startswith("postgresql+psycopg") and "sslmode" not in q:
        q["sslmode"] = ["require"]
        uri = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return uri

# On utilise le db des models (source de vérité)
from models import (
    db, User, Professional, Appointment,
    ProfessionalAvailability, UnavailableSlot,
    City, Specialty,
)

uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL") or ""
if not uri:
    raise RuntimeError("DATABASE_URL manquant : lie ta base Postgres dans Render.")
app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_pg_uri(uri)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
db.init_app(app)

# ========== Admin (Blueprint) ==========
from admin_server import admin_bp, ProfessionalOrder, _build_notif
app.register_blueprint(admin_bp, url_prefix="/admin")

# ========== Login Manager ==========
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

@login_manager.user_loader
def _load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

# ========== OAuth Google ==========
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

# ========== Langue ==========
def _normalize_lang(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    code = code.lower().strip()
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG

@app.before_request
def _load_locale():
    lang = _normalize_lang(request.cookies.get(LANG_COOKIE))
    g.current_locale = lang
    g.current_locale_label = {"fr": "Français", "ar": "العربية", "en": "English"}.get(lang, "Français")

@app.route('/set-language/<lang>', methods=['GET'], endpoint='set_language')
@app.route('/set-language', methods=['GET'], endpoint='set_language')
def set_language(lang: str | None = None):
    lang = _normalize_lang(lang or request.args.get('lang') or request.args.get('lang_code'))
    resp = make_response(redirect(request.referrer or url_for('index')))
    resp.set_cookie(LANG_COOKIE, lang, max_age=60*60*24*180, samesite="Lax", secure=True)
    return resp

# Listes dynamiques injectées partout
@lru_cache(maxsize=1)
def _load_refdata_snapshot():
    try:
        cities = [c.name for c in db.session.query(City).order_by(City.name.asc()).all()]
        specialties = [s.name for s in db.session.query(Specialty).order_by(Specialty.name.asc()).all()]
    except Exception:
        cities, specialties = [], []
    return tuple(cities), tuple(specialties)

@app.context_processor
def inject_refdata_lists():
    cities, specialties = _load_refdata_snapshot()
    return {"ALL_CITIES": list(cities), "ALL_SPECIALTIES": list(specialties)}

# ========== Helpers images ==========
AVATAR_DIR = os.path.join(app.root_path, "static", "avatars")
PLACEHOLDER_AVATAR = os.path.join(app.root_path, "static", "avatar_default.webp")

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _process_and_save_profile_image(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _ext_ok(filename):
        raise ValueError("Extension non autorisée")
    raw = file_storage.read()
    if not _PIL_OK:
        raise RuntimeError("Le traitement d'image nécessite Pillow (PIL).")
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
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

def _avatar_file_for(pid: int) -> Optional[str]:
    if not os.path.isdir(AVATAR_DIR):
        return None
    for ext in (".webp", ".jpg", ".jpeg", ".png"):
        path = os.path.join(AVATAR_DIR, f"{pid}{ext}")
        if os.path.isfile(path):
            return path
    return None

PHOTO_PLACEHOLDER = "https://placehold.co/600x600?text=Photo"
AVATAR_DEFAULT_REL = "img/avatar-default.png"

def _avatar_fallback_response():
    static_avatar = Path(app.static_folder or (BASE_DIR / "static")) / AVATAR_DEFAULT_REL
    if static_avatar.exists():
        resp = send_from_directory(app.static_folder, AVATAR_DEFAULT_REL, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    return redirect(PHOTO_PLACEHOLDER)

@app.route("/media/profiles/<path:filename>", methods=["GET"])
def media_profiles_file(filename: str):
    safe_name = os.path.basename(filename)
    fpath = UPLOAD_FOLDER / safe_name
    if fpath.exists():
        resp = send_from_directory(str(UPLOAD_FOLDER), safe_name, as_attachment=False, conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=31536000"
        return resp
    return _avatar_fallback_response()

# ========== Routes techniques ==========
@app.route("/favicon.ico")
def favicon():
    fav_path = Path(app.static_folder or (BASE_DIR / "static")) / "favicon.ico"
    if fav_path.exists():
        resp = send_from_directory(app.static_folder, "favicon.ico", conditional=True)
        resp.headers["Cache-Control"] = "public, max-age=604800"
        return resp
    return ("", 204)

@app.route("/robots.txt")
def robots():
    txt_path = Path(app.static_folder or (BASE_DIR / "static")) / "robots.txt"
    if txt_path.exists():
        return send_from_directory(app.static_folder, "robots.txt", mimetype="text/plain")
    return ("User-agent: *\nDisallow:\n", 200, {"Content-Type": "text/plain"})

# ========== Pages publiques ==========
@app.route("/", endpoint="index")
def index():
    # Tri admin si table d’ordre dispo, sinon fallback
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

    return render_template("index.html",
        top_professionals=top_professionals,
        more_professionals=more_professionals
    )

@app.route("/anthecc", endpoint="anthecc")
def anthecc():
    return render_template("anthecc.html")

@app.route("/about", endpoint="about")
def about():
    return render_template("about.html")

@app.route("/contact", endpoint="contact")
def contact():
    return render_template("contact.html")

# Listing / recherche
@app.route("/professionals", endpoint="professionals")
def professionals():
    q = (request.args.get("q") or "").strip()
    city = (request.args.get("city") or "").strip()
    specialty = (request.args.get("specialty") or "").strip()
    mode = (request.args.get("mode") or "").strip().lower()

    # Nouveaux filtres par ID (si selects dynamiques)
    city_id = request.args.get("city_id", type=int)
    specialty_id = request.args.get("specialty_id", type=int)

    # normaliser le terme du mode
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

    if city_id and hasattr(Professional, "city_id"):
        qry = qry.filter(Professional.city_id == city_id)
    elif city and hasattr(Professional, "location"):
        qry = qry.filter(Professional.location.ilike(f"%{city}%"))

    if specialty_id and hasattr(Professional, "primary_specialty_id"):
        qry = qry.filter(Professional.primary_specialty_id == specialty_id)
    elif specialty and hasattr(Professional, "specialty"):
        qry = qry.filter(Professional.specialty.ilike(f"%{specialty}%"))

    if mode and hasattr(Professional, "consultation_types"):
        qry = qry.filter(Professional.consultation_types.ilike(f"%{mode}%"))

    pros = qry.order_by(Professional.is_featured.desc(), Professional.created_at.desc()).all()
    return render_template("professionals.html", professionals=pros, specialty=specialty, search_query=q)

# Fiche pro
@app.route("/professional/<int:professional_id>", endpoint="professional_detail")
def professional_detail(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    return render_template("professional_detail.html", professional=professional)

# ========== Photos / médias ==========
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

    headers = {"User-Agent": "Mozilla/5.0 (compatible; TighriBot/1.0; +https://www.tighri.com)", "Referer": "https://www.tighri.com"}
    try:
        r = requests.get(raw_url, headers=headers, timeout=8, stream=True)
        r.raise_for_status()
    except Exception:
        return _avatar_fallback_response()

    content_type = r.headers.get("Content-Type", "image/jpeg")
    resp = Response(r.content, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp

@app.route("/avatar", endpoint="avatar")
def avatar_alias_qs():
    pid = request.args.get("professional_id", type=int)
    if not pid:
        return _avatar_fallback_response()
    return redirect(url_for("profile_photo", professional_id=pid))

@app.route("/avatar/<int:professional_id>")
def avatar_alias_path(professional_id: int):
    return redirect(url_for("profile_photo", professional_id=professional_id))

# Upload photo pro (ancienne route – conservée, pour image principale)
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
        # On accepte 3 champs: photo (principale), photo2, photo3
        mapping = [
            ("photo",  "image_url"),
            ("photo2", "image_url2"),
            ("photo3", "image_url3"),
        ]

        changed_any = False
        try:
            for field_name, attr in mapping:
                file = request.files.get(field_name)
                if file and getattr(file, "filename", ""):
                    saved_name = _process_and_save_profile_image(file)
                    setattr(pro, attr, f"/media/profiles/{saved_name}")
                    changed_any = True

            if changed_any:
                db.session.commit()
                flash("Photo(s) mise(s) à jour avec succès.", "success")
            else:
                flash("Aucune image sélectionnée.", "warning")

            return redirect(url_for("professional_edit_profile"))

        except RuntimeError:
            current_app.logger.exception("PIL manquant pour traitement image.")
            flash("Le traitement d'image nécessite Pillow.", "danger")
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            current_app.logger.exception("Erreur interne lors du traitement de l'image")
            flash("Erreur interne lors du traitement de l'image.", "danger")
return render_template("upload_photo.html", professional=pro)



# ========== Auth local ==========
@app.route("/register", methods=["GET","POST"], endpoint="register")
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
        flash("Compte patient créé avec succès!")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/professional_register", methods=["GET","POST"], endpoint="professional_register")
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
            db.session.add(professional)
            db.session.commit()
        except Exception:
            db.session.rollback()
            flash("Erreur lors de la création du compte professionnel. Réessayez.", "danger")
            return redirect(url_for("professional_register"))

        flash("Compte professionnel créé avec succès! Un administrateur validera votre profil.")
        return redirect(url_for("login"))

    return render_template("professional_register.html")

@app.route("/login", methods=["GET","POST"], endpoint="login")
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
            return redirect(url_for("professional_dashboard" if user.user_type == "professional" else "index"))

        flash("Nom d'utilisateur / email ou mot de passe incorrect")
    return render_template("login.html")

@app.route("/logout", endpoint="logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

# ========== OAuth Google ==========
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
        return redirect(url_for("professional_dashboard" if user.user_type == "professional" else "index"))

    except Exception:
        flash("Connexion Google impossible. Réessayez.", "danger")
        return redirect(url_for("login"))

# ========== Mot de passe : reset ==========
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
    return render_template("change_password.html")

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
    return render_template("forgot_password.html")

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
    return render_template("reset_password.html")

# ========== Espace pro / RDV ==========
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
    return render_template("professional_dashboard.html",
                           professional=professional, appointments=appointments)

# Dispos hebdo
@app.route("/professional/availability", methods=["GET","POST"], endpoint="professional_availability")
@login_required
def professional_availability():
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

    return render_template("professional_availability.html",
                           professional=professional,
                           availabilities=availability_dict,
                           windows_by_day=windows_by_day)

# Indisponibilités ponctuelles
@app.route("/professional/unavailable-slots", methods=["GET","POST"], endpoint="professional_unavailable_slots")
@login_required
def professional_unavailable_slots():
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
    return render_template("professional_unavailable_slots.html",
                           professional=professional, unavailable_slots=unavailable_slots)

@app.route("/professional/unavailable-slots/<int:slot_id>/delete", methods=["POST"], endpoint="delete_unavailable_slot")
@login_required
def delete_unavailable_slot(slot_id: int):
    if current_user.user_type != "professional":
        flash("Accès non autorisé"); return redirect(url_for("index"))
    professional = Professional.query.filter_by(name=current_user.username).first()
    if not professional:
        flash("Profil professionnel non trouvé"); return redirect(url_for("index"))
    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional.id:
        flash("Accès non autorisé"); return redirect(url_for("professional_unavailable_slots"))
    db.session.delete(slot); db.session.commit()
    flash("Créneau indisponible supprimé!")
    return redirect(url_for("professional_unavailable_slots"))

# --- ROUTE: édition du profil pro ---
@app.route("/professional/profile", methods=["GET", "POST"], endpoint="professional_edit_profile")
@login_required
def professional_edit_profile():
    professional = Professional.query.filter_by(name=current_user.username).first()
    if professional is None:
        flash("Profil professionnel non trouvé", "warning")
        return redirect(url_for("professional_dashboard"))

    if request.method == "POST":
        f = request.form

        city_sel = (f.get("city") or "").strip()
        if city_sel:
            professional.location = city_sel

        professional.name = (f.get("name") or "").strip() or professional.name
        professional.specialty = (f.get("specialty") or "").strip() or None
        professional.description = (f.get("description") or "").strip() or None
        professional.location = (f.get("location") or "").strip() or None
        professional.address = (f.get("address") or "").strip() or None
        professional.phone = (f.get("phone") or "").strip() or None

        # Option B : si le formulaire envoie des champs URL supplémentaires
        if hasattr(Professional, "image_url"):
            professional.image_url = (f.get("image_url") or "").strip() or professional.image_url
        if hasattr(Professional, "image_url2"):
            professional.image_url2 = (f.get("image_url2") or "").strip() or None
        if hasattr(Professional, "image_url3"):
            professional.image_url3 = (f.get("image_url3") or "").strip() or None

        def to_float(v):
            try:
                v = (v or "").strip()
                return float(v.replace(",", ".")) if v else None
            except Exception:
                return None

        def to_int(v):
            try:
                v = (v or "").strip()
                return int(v) if v else None
            except Exception:
                return None

        professional.latitude  = to_float(f.get("latitude"))
        professional.longitude = to_float(f.get("longitude"))
        professional.consultation_fee = to_float(f.get("consultation_fee"))
        professional.consultation_duration_minutes = to_int(f.get("consultation_duration_minutes")) or 45
        professional.buffer_between_appointments_minutes = to_int(f.get("buffer_between_appointments_minutes")) or 15

        types = f.getlist("consultation_types")
        professional.consultation_types = ",".join(sorted(set(t for t in types if t)))

        old_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        professional.facebook_url  = (f.get("facebook_url") or "").strip() or None
        professional.instagram_url = (f.get("instagram_url") or "").strip() or None
        professional.tiktok_url    = (f.get("tiktok_url") or "").strip() or None
        professional.youtube_url   = (f.get("youtube_url") or "").strip() or None
        new_links = (
            (professional.facebook_url or ""),
            (professional.instagram_url or ""),
            (professional.tiktok_url or ""),
            (professional.youtube_url or ""),
        )
        if new_links != old_links:
            professional.social_links_approved = False

        db.session.commit()
        flash("Profil mis à jour.", "success")
        return redirect(url_for("professional_dashboard"))

    return render_template("professional_edit_profile.html", professional=professional)

# Alias “voir mes RDV”
@app.route("/professional/appointments", endpoint="professional_appointments")
@login_required
def professional_appointments():
    return redirect(url_for("my_appointments"))

@app.route("/my_appointments", endpoint="my_appointments")
@login_required
def my_appointments():
    if current_user.user_type == "professional":
        appointments = Appointment.query.join(Professional).filter(Professional.name == current_user.username).all()
    else:
        appointments = Appointment.query.filter_by(patient_id=current_user.id).all()
    return render_template("my_appointments.html", appointments=appointments)

# Réservation
def _str_to_time(hhmm: str) -> dtime:
    return datetime.strptime(hhmm, "%H:%M").time()

def _add_minutes(t: dtime, minutes: int) -> dtime:
    return (datetime.combine(date.today(), t) + timedelta(minutes=minutes)).time()

def _overlap(start1: dtime, end1: dtime, start2: dtime, end2: dtime) -> bool:
    return start1 < end2 and start2 < end1

@app.route("/book_appointment/<int:professional_id>", methods=["GET","POST"], endpoint="book_appointment")
@login_required
def book_appointment(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    if professional.status != "valide":
        flash("Ce professionnel n'est pas encore validé par l'administration.")
        return redirect(url_for("professionals"))

    duration = int(getattr(professional, "consultation_duration_minutes", 45) or 45)

    if request.method == "POST":
        appointment_date = request.form.get("appointment_date", "")
        appointment_time = request.form.get("appointment_time", "")
        consultation_type = request.form.get("consultation_type", "cabinet")
        notes = request.form.get("notes", "")

        try:
            appointment_date_obj = datetime.strptime(appointment_date, "%Y-%m-%d").date()
        except ValueError:
            flash("Format de date invalide."); return redirect(url_for("book_appointment", professional_id=professional_id))
        if appointment_date_obj < date.today():
            flash("Impossible de réserver un rendez-vous dans le passé.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        try:
            appointment_datetime = datetime.strptime(f"{appointment_date} {appointment_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            flash("Format de date/heure invalide.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        day_of_week = appointment_datetime.weekday()
        availabilities = ProfessionalAvailability.query.filter_by(
            professional_id=professional_id, day_of_week=day_of_week, is_available=True
        ).all()

        start_t = appointment_datetime.time()
        end_t = _add_minutes(start_t, duration)

        inside_any_window = any(
            (_str_to_time(av.start_time) <= start_t) and (end_t <= _str_to_time(av.end_time))
            for av in availabilities
        )
        if not inside_any_window:
            flash("Cette heure n'est pas disponible pour ce professionnel.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        existing_confirmed = Appointment.query.filter_by(professional_id=professional_id, status="confirme")\
            .filter(db.func.date(Appointment.appointment_date) == appointment_date_obj).all()
        if any(_overlap(start_t, end_t, a.appointment_date.time(), _add_minutes(a.appointment_date.time(), duration))
               for a in existing_confirmed):
            flash("Ce créneau est déjà réservé.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        day_unavailable = UnavailableSlot.query.filter_by(professional_id=professional_id, date=appointment_date_obj).all()
        if any(_overlap(start_t, end_t, _str_to_time(s.start_time), _str_to_time(s.end_time)) for s in day_unavailable):
            flash("Ce créneau est marqué comme indisponible.")
            return redirect(url_for("book_appointment", professional_id=professional_id))

        appointment = Appointment(
            patient_id=current_user.id, professional_id=professional_id,
            appointment_date=appointment_datetime, consultation_type=consultation_type,
            status="en_attente", notes=notes
        )
        db.session.add(appointment); db.session.commit()

        try:
            subject, text = _build_notif("pending", appointment, role="patient")
            safe_send_email(current_user.email, subject, text)
        except Exception:
            pass
        try:
            pro_user = User.query.filter_by(username=professional.name).first()
            if pro_user and pro_user.email:
                subject, text = _build_notif("pending", appointment, role="pro")
                safe_send_email(pro_user.email, subject, text)
        except Exception:
            pass

        flash("Rendez-vous réservé avec succès! Le professionnel confirmera bientôt.")
        return redirect(url_for("my_appointments"))

    availabilities = ProfessionalAvailability.query.filter_by(professional_id=professional_id, is_available=True).all()
    today = date.today()
    unavailable_dates = [
        (today + timedelta(days=i)).isoformat()
        for i in range(30)
        if UnavailableSlot.query.filter_by(professional_id=professional_id, date=(today + timedelta(days=i))).first()
    ]
    return render_template("book_appointment.html",
                           professional=professional,
                           availabilities=availabilities,
                           unavailable_dates=unavailable_dates)

# API slots
@app.route("/api/professional/<int:professional_id>/available-slots", endpoint="api_available_slots")
def api_available_slots(professional_id: int):
    professional = Professional.query.get_or_404(professional_id)
    if professional.status != "valide":
        return jsonify({"error": "Professionnel non validé"}), 400

    requested_date = request.args.get("date", date.today().isoformat())
    try:
        target_date = datetime.strptime(requested_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Format de date invalide"}), 400

    day_of_week = target_date.weekday()
    availabilities = ProfessionalAvailability.query.filter_by(
        professional_id=professional_id, day_of_week=day_of_week, is_available=True
    ).all()
    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional_id, date=target_date).all()
    confirmed = Appointment.query.filter_by(professional_id=professional_id, status="confirme")\
        .filter(db.func.date(Appointment.appointment_date) == target_date).all()

    duration = int(getattr(professional, "consultation_duration_minutes", 45) or 45)
    buffer_m = int(getattr(professional, "buffer_between_appointments_minutes", 15) or 15)
    step = max(1, duration + buffer_m)

    def _slots():
        out = []
        for av in availabilities:
            start_time = _str_to_time(av.start_time)
            end_time = _str_to_time(av.end_time)
            current = start_time
            while _add_minutes(current, duration) <= end_time:
                slot_start = current
                slot_end = _add_minutes(current, duration)
                is_unavailable = any(_overlap(slot_start, slot_end, _str_to_time(u.start_time), _str_to_time(u.end_time))
                                     for u in unavailable_slots)
                is_booked = any(_overlap(slot_start, slot_end, a.appointment_date.time(), _add_minutes(a.appointment_date.time(), duration))
                                for a in confirmed)
                if not is_unavailable and not is_booked:
                    out.append({"start_time": slot_start.strftime("%H:%M"),
                                "end_time": slot_end.strftime("%H:%M"),
                                "available": True})
                current = _add_minutes(current, step)
        return out

    return jsonify({
        "professional_id": professional_id,
        "date": target_date.isoformat(),
        "duration_minutes": duration,
        "buffer_minutes": buffer_m,
        "available_slots": _slots()
    })

# ========== Statut site ==========
@app.route("/site-status", endpoint="site_status")
def site_status():
    status = app.config.get("SITE_STATUS", {})
    stats = {
        "total_professionals": Professional.query.count(),
        "total_users": User.query.count(),
        "total_appointments": Appointment.query.count(),
    }
    return render_template("site_status.html", status=status, stats=stats)

# ========== Erreurs ==========
@app.errorhandler(404)
def not_found(e):
    return render_template("errors/404.html"), 404

@app.errorhandler(500)
def server_error(e):
    return render_template("errors/500.html"), 500

# ========== Boot (migrations légères + admin seed) ==========
with app.app_context():
    db.create_all()
    try:
        for sql in [
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
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url2 TEXT;",
            "ALTER TABLE professionals ADD COLUMN IF NOT EXISTS image_url3 TEXT;",

            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_provider VARCHAR(30);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS oauth_sub VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture_url TEXT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(120);",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_oauth_sub ON users(oauth_sub);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_hash VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires_at TIMESTAMP;",
        ]:
            db.session.execute(text(sql))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Mini-migration colonnes: {e}")

    # Seed villes (si table Cities utilisée)
    try:
        _cities = [
            "Casablanca","Rabat","Fès","Marrakech","Tanger","Agadir","Meknès","Oujda",
            "Kénitra","Tétouan","Safi","Mohammedia","El Jadida","Béni Mellal","Nador",
            "Taza","Khouribga","Settat","Larache","Ksar El Kébir","Guelmim","Laâyoune",
            "Dakhla","Errachidia","Ouarzazate","Taroudant","Essaouira","Berkane","Taourirt",
            "Guercif","Sidi Kacem","Sidi Slimane","Tiflet","Skhirat","Temara","Salé",
            "Inezgane","Aït Melloul","Fkih Ben Salah","Youssoufia","Azemmour","Berrechid",
            "Médiouna","Bouznika","Bouskoura","Sidi Bennour","Chichaoua","El Kelaa des Sraghna",
            "Ifrane","Midelt","Azrou","Khénifra","Ouezzane","Chefchaouen","Al Hoceima",
            "Tinghir","Zagora","Smara","Boujdour"
        ]
        for name in _cities:
            if not City.query.filter_by(name=name).first():
                db.session.add(City(name=name))
        db.session.commit()
    except Exception as e:
        app.logger.warning(f"Seed cities ignoré: {e}")

    # seed admin
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

# Filet de sécurité: alias si l'endpoint attendu par le template n'existe pas
if 'professional_edit_profile' not in app.view_functions:
    @app.route('/professional/profile', methods=['GET', 'POST'], endpoint='professional_edit_profile')
    @login_required
    def _professional_edit_profile_alias():
        flash("Redirection vers votre espace professionnel.", "info")
        return redirect(url_for('professional_dashboard'))

# Pas de __main__ : Gunicorn lance app:app
