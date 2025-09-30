# admin_server.py — Blueprint d'administration Tighri (une seule instance Flask dans app.py)
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, date
from pathlib import Path
import os, io, uuid

# PIL pour l'upload image (même logique que côté app.py)
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot

admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder=None)

# ===== Helpers image (admin) =================================================
ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif'}

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _admin_upload_dir() -> Path:
    """
    Utilise le même dossier que l'app :
    1) Si app.config['UPLOAD_FOLDER'] est défini : on l'utilise (→ /var/data/... en prod)
    2) Sinon, si /var/data existe : on s'en sert (prod Render)
    3) Sinon, fallback local <root>/uploads/profiles
    """
    cfg = current_app.config.get('UPLOAD_FOLDER')
    if cfg:
        up = Path(cfg)
    else:
        var_data = Path("/var/data")
        if var_data.exists():
            up = var_data / "uploads" / "profiles"
        else:
            up = Path(current_app.root_path).parent / "uploads" / "profiles"
    up.mkdir(parents=True, exist_ok=True)
    return up

def _admin_process_and_save_profile_image(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _ext_ok(filename):
        raise ValueError("Extension non autorisée")

    if not _PIL_OK:
        raise RuntimeError("Pillow n'est pas installé sur le serveur.")

    raw = file_storage.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
    except Exception:
        raise ValueError("Fichier image invalide ou corrompu")

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    # strip exif
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))

    TARGET_SIZE = (512, 512)
    img_square = ImageOps.fit(img_no_exif, TARGET_SIZE, Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = _admin_upload_dir() / out_name
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_name
# ============================================================================

# ===== Helpers NOTIF (admin) ================================================
def _split_emails(raw: str) -> list[str]:
    vals = []
    for chunk in (raw or "").replace(";", ",").split(","):
        x = chunk.strip()
        if x:
            vals.append(x)
    return list(dict.fromkeys(vals))

def _admin_recipients() -> list[str]:
    return _split_emails(os.getenv("ADMIN_NOTIF_EMAILS") or os.getenv("ADMIN_EMAIL") or "")

def _smtp_env_ok() -> bool:
    host = os.getenv("EMAIL_HOST") or os.getenv("MAIL_SERVER")
    user = os.getenv("EMAIL_USER") or os.getenv("MAIL_USERNAME")
    pw   = os.getenv("EMAIL_PASS") or os.getenv("MAIL_PASSWORD")
    sender = os.getenv("EMAIL_FROM") or os.getenv("MAIL_DEFAULT_SENDER") or user
    ok = bool(host and user and pw and sender)
    if not ok:
        current_app.logger.warning(
            "[ADMIN][NOTIF][EMAIL] Configuration SMTP incomplète (EMAIL_* / MAIL_*). "
            "EMAIL_HOST/USER/PASS/FROM ou MAIL_SERVER/MAIL_USERNAME/MAIL_PASSWORD/MAIL_DEFAULT_SENDER requis."
        )
    return ok

def _safe_send_email_admin(to_addr: str | None, subject: str, body: str):
    if not to_addr:
        current_app.logger.info("[ADMIN][NOTIF][EMAIL] destinataire manquant (skip) — %s", subject)
        return
    try:
        from notifications import send_email
        if not _smtp_env_ok():
            pass
        ok = send_email(to_addr, subject, body)
        if ok:
            current_app.logger.info("[ADMIN][NOTIF][EMAIL] envoyé → %s : %s", to_addr, subject)
        else:
            current_app.logger.warning("[ADMIN][NOTIF][EMAIL] échec (send_email=False) → %s : %s", to_addr, subject)
    except Exception as e:
        current_app.logger.warning("[ADMIN][NOTIF][EMAIL] exception: %s", e)

def _notify_admin_event(subject: str, body: str):
    for admin_mail in _admin_recipients():
        _safe_send_email_admin(admin_mail, subject, body)

# Messages RDV (utilisés aussi côté app.py via import)
def _build_notif(kind: str, ap: Appointment, role: str = 'patient') -> tuple[str, str]:
    dt = ap.appointment_date.strftime('%d/%m/%Y %H:%M')
    pro = ap.professional
    who = f"{pro.name} — {pro.specialty or ''}".strip() if pro else "le professionnel"
    if kind == 'pending':
        if role == 'patient':
            return ("Votre RDV est en attente de confirmation",
                    f"Bonjour,\n\nVotre demande de RDV ({dt}) avec {who} est bien enregistrée et en attente de confirmation.\n\nTighri")
        else:
            return ("Nouveau RDV à confirmer",
                    f"Bonjour,\n\nNouveau RDV à confirmer le {dt} avec le patient #{ap.patient_id}.\n\nTighri")
    if kind == 'accepted':
        return ("Votre RDV est confirmé",
                f"Bonjour,\n\nVotre RDV le {dt} avec {who} est CONFIRMÉ.\n\nTighri")
    if kind == 'refused':
        return ("Votre RDV a été annulé",
                f"Bonjour,\n\nVotre RDV le {dt} avec {who} a été annulé.\n\nTighri")
    if kind == 'reminder':
        if role == 'patient':
            return ("Rappel : votre RDV est dans 24h",
                    f"Bonjour,\n\nRappel : RDV le {dt} avec {who} dans ~24h.\n\nTighri")
        else:
            return ("Rappel : RDV (pro) dans 24h",
                    f"Bonjour,\n\nRappel : vous avez un RDV le {dt} (patient #{ap.patient_id}).\n\nTighri")
    return ("Notification", f"Bonjour,\n\nMise à jour RDV ({dt}).\n\nTighri")

def _notify_patient(kind: str, ap: Appointment):
    subject, text = _build_notif(kind, ap, role='patient')
    user = User.query.get(ap.patient_id)
    _safe_send_email_admin(getattr(user, 'email', None), subject, text)

def _notify_pro(kind: str, ap: Appointment):
    pro = ap.professional or Professional.query.get(ap.professional_id)
    if not pro:
        return
    subject, text = _build_notif(kind, ap, role='pro')
    pro_user = None
    try:
        pro_user = User.query.filter_by(username=pro.name).first()
    except Exception:
        pro_user = None
    _safe_send_email_admin(getattr(pro_user, 'email', None), subject, text)

def _notify_admin_for_appointment(kind: str, ap: Appointment):
    dt = ap.appointment_date.strftime('%d/%m/%Y %H:%M')
    pro = ap.professional or Professional.query.get(ap.professional_id)
    who = f"{pro.name} — {pro.specialty or ''}".strip() if pro else f"pro #{ap.professional_id}"
    subject = f"[ADMIN] RDV {kind} · {dt} · {who}"
    body = f"RDV {kind} pour le {dt}\nPro: {who}\nPatient id: {ap.patient_id}\nID RDV: {ap.id}"
    _notify_admin_event(subject, body)

# ===== Helpers NOTIF comptes (admin) ========================================
def _build_account_notif(kind: str, user: User | None = None, pro: Professional | None = None) -> tuple[str, str]:
    if kind == "account_created":
        return ("Bienvenue sur Tighri",
                "Bonjour,\n\nVotre compte a été créé sur Tighri. Vous pouvez vous connecter et compléter votre profil.\n\nTighri")
    if kind == "account_updated":
        return ("Votre compte a été mis à jour",
                "Bonjour,\n\nVotre compte vient d'être modifié par l'administration. Si vous n'êtes pas à l'origine de cette action, contactez-nous.\n\nTighri")
    if kind == "pro_validated":
        name = (pro.name if pro else "Votre profil")
        return ("Profil professionnel validé",
                f"Bonjour,\n\n{name} a été validé. Votre profil est désormais visible et réservable.\n\nTighri")
    if kind == "pro_rejected":
        return ("Profil professionnel rejeté",
                "Bonjour,\n\nVotre profil professionnel a été rejeté. Vous pouvez corriger vos informations et demander une nouvelle validation.\n\nTighri")
    if kind == "social_links_approved":
        return ("Liens sociaux approuvés",
                "Bonjour,\n\nVos liens sociaux ont été approuvés par l’administration.\n\nTighri")
    if kind == "social_links_unapproved":
        return ("Liens sociaux mis en attente",
                "Bonjour,\n\nVos liens sociaux ne sont pas/plus approuvés. Merci d’ajuster vos liens si nécessaire.\n\nTighri")
    return ("Notification compte", "Bonjour,\n\nMise à jour de votre compte.\n\nTighri")

def _notify_user_account(email: str | None, kind: str, pro: Professional | None = None):
    subject, text = _build_account_notif(kind, pro=pro)
    _safe_send_email_admin(email, subject, text)

# --------------------- AUTH ADMIN ---------------------
@admin_bp.route('/login', methods=['GET', 'POST'], endpoint='admin_login')
def admin_login():
    if request.method == 'POST':
        username_or_email = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '')

        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email.lower())
        ).first()

        if user and user.is_admin and check_password_hash(user.password_hash, password):
            remember = bool(request.form.get('remember'))
            login_user(user, remember=remember)
            next_url = (request.form.get('next') or '').strip()
            return redirect(next_url or url_for('admin.admin_dashboard'))
        else:
            flash('Identifiants incorrects ou accès non autorisé', 'error')

    return render_template('admin_login.html')

@admin_bp.route('/logout', endpoint='admin_logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin.admin_login'))

# --------------------- DASHBOARD ---------------------
@admin_bp.route('/', endpoint='admin_dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    professionals = Professional.query.order_by(Professional.id.desc()).all()
    users = User.query.order_by(User.id.desc()).all()
    appointments = Appointment.query.order_by(Appointment.appointment_date.desc()).all()

    total_professionals = len(professionals)
    total_users = len(users)
    total_appointments = len(appointments)
    total_revenue = sum(
        (a.professional.consultation_fee or 0)
        for a in appointments
        if a.status == 'confirme' and a.professional
    )

    return render_template(
        'admin_dashboard.html',
        professionals=professionals,
        users=users,
        appointments=appointments,
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        total_revenue=total_revenue
    )

# --------------------- Classement (table dédiée, pas de FK pour éviter l'erreur au boot) ---------------------
class ProfessionalOrder(db.Model):
    __tablename__ = 'professional_order'
    professional_id = db.Column(db.Integer, primary_key=True)  # <-- pas de ForeignKey ici
    order_priority = db.Column(db.Integer, nullable=False, default=9999)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

def _ensure_order_table():
    ProfessionalOrder.__table__.create(bind=db.engine, checkfirst=True)

def _load_order_map() -> dict[int, int]:
    rows = ProfessionalOrder.query.all()
    return {r.professional_id: (r.order_priority if r.order_priority is not None else 9999) for r in rows}

@admin_bp.route('/professionals/order', methods=['GET', 'POST'], endpoint='admin_professional_order')
@login_required
def admin_professional_order():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    _ensure_order_table()

    if request.method == 'POST':
        updated = 0
        for key, val in request.form.items():
            if not key.startswith('order_priority_'):
                continue
            try:
                pro_id = int(key.split('_')[-1])
            except ValueError:
                continue
            try:
                priority = int(val.strip()) if (val is not None and val.strip() != '') else 9999
            except ValueError:
                priority = 9999

            row = ProfessionalOrder.query.get(pro_id)
            if row is None:
                row = ProfessionalOrder(professional_id=pro_id, order_priority=priority)
                db.session.add(row)
            else:
                row.order_priority = priority
            updated += 1

        db.session.commit()
        flash(f"Classement mis à jour pour {updated} professionnels.")
        return redirect(url_for('admin.admin_professional_order'))

    orders = _load_order_map()
    professionals = Professional.query.all()

    professionals_sorted = sorted(
        professionals,
        key=lambda p: (orders.get(p.id, 9999), (p.name or '').lower())
    )

    for p in professionals_sorted:
        setattr(p, 'order_priority', orders.get(p.id, 9999))

    return render_template(
        'admin_professional_order.html',
        professionals=professionals_sorted,
        orders=orders
    )

# --------------------- PROFESSIONNELS (liste type "products") ---------------------
@admin_bp.route('/products', endpoint='admin_products')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    professionals = Professional.query.order_by(Professional.id.desc()).all()
    return render_template('admin_products.html', professionals=professionals)

@admin_bp.route('/products/add', methods=['GET', 'POST'], endpoint='admin_add_product')
@login_required
def admin_add_product():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        specialty = (request.form.get('specialty') or request.form.get('category') or '').strip()
        city_or_location = (request.form.get('location') or '').strip()
        image_url = (request.form.get('image_url') or '').strip()
        image_url2 = (request.form.get('image_url2') or '').strip()
        image_url3 = (request.form.get('image_url3') or '').strip()
        phone = (request.form.get('phone') or '').strip()

        # adresse / géoloc
        address = (request.form.get('address') or '').strip()
        lat_raw = (request.form.get('latitude') or '').strip()
        lng_raw = (request.form.get('longitude') or '').strip()
        try:
            latitude = float(lat_raw) if lat_raw else None
        except ValueError:
            latitude = None
            flash("Latitude invalide", "error")
        try:
            longitude = float(lng_raw) if lat_raw else None
        except ValueError:
            longitude = None
            flash("Longitude invalide", "error")

        # tarif / expérience
        fee_raw = (request.form.get('price') or request.form.get('consultation_fee') or '0').replace(',', '.')
        try:
            consultation_fee = float(fee_raw)
        except ValueError:
            consultation_fee = 0.0

        exp_raw = request.form.get('experience_years') or '0'
        try:
            experience_years = int(exp_raw)
        except ValueError:
            experience_years = 0

        # dispo
        availability = request.form.get('availability')
        if availability is None:
            stock = (request.form.get('stock') or '').strip().lower()
            availability = 'disponible' if stock in ('1', 'true', 'on', 'yes') else 'indisponible'

        # Types de consultation
        types_list = request.form.getlist('consultation_types')
        if not types_list:
            types_list = []
            if request.form.get('home_consultation'): types_list.append('domicile')
            if request.form.get('office_consultation'): types_list.append('cabinet')
            if request.form.get('online_consultation'): types_list.append('en_ligne')
        consultation_types = ','.join(types_list) if types_list else 'cabinet'

        # Réseaux sociaux (URLs + approbation)
        facebook_url  = (request.form.get('facebook_url')  or '').strip()
        instagram_url = (request.form.get('instagram_url') or '').strip()
        tiktok_url    = (request.form.get('tiktok_url')    or '').strip()
        youtube_url   = (request.form.get('youtube_url')   or '').strip()
        social_links_approved = bool(request.form.get('social_links_approved'))

        # durée/buffer
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        try:
            consultation_duration_minutes = max(5, min(240, int(dur_raw))) if dur_raw else 45
        except ValueError:
            consultation_duration_minutes = 45
        try:
            buffer_between_appointments_minutes = max(0, min(120, int(buf_raw))) if buf_raw else 15
        except ValueError:
            buffer_between_appointments_minutes = 15

        # upload fichier image (optionnel)
        file = request.files.get('image_file')
        if file and getattr(file, 'filename', ''):
            try:
                saved = _admin_process_and_save_profile_image(file)
                image_url = f"/media/profiles/{saved}"
            except Exception as e:
                flash(f"Image non enregistrée ({e}).", "warning")
file2 = request.files.get('image_file2')
if file2 and getattr(file2, 'filename', ''):
    try:
        saved2 = _admin_process_and_save_profile_image(file2)
        image_url2 = f"/media/profiles/{saved2}"
    except Exception as e:
        flash(f"Image 2 non enregistrée ({e}).", "warning")

file3 = request.files.get('image_file3')
if file3 and getattr(file3, 'filename', ''):
    try:
        saved3 = _admin_process_and_save_profile_image(file3)
        image_url3 = f"/media/profiles/{saved3}"
    except Exception as e:
        flash(f"Image 3 non enregistrée ({e}).", "warning")

        if not name or not specialty:
            flash("Nom et spécialité sont obligatoires.", "error")
            return redirect(url_for('admin.admin_add_product'))

        professional = Professional(
            name=name,
            description=description,
            consultation_fee=consultation_fee,
            image_url=image_url,
            image_url2=image_url2 or None,
            image_url3=image_url3 or None,
            specialty=specialty,
            availability=availability,
            consultation_types=consultation_types,
            location=city_or_location or 'Casablanca',
            phone=phone or None,
            experience_years=experience_years,
            address=address or None,
            latitude=latitude,
            longitude=longitude,
            facebook_url=facebook_url or None,
            instagram_url=instagram_url or None,
            tiktok_url=tiktok_url or None,
            youtube_url=youtube_url or None,
            social_links_approved=social_links_approved,
            status='en_attente',
            consultation_duration_minutes=consultation_duration_minutes,
            buffer_between_appointments_minutes=buffer_between_appointments_minutes,
        )
        db.session.add(professional)
        db.session.commit()
        flash('Professionnel ajouté avec succès!')
        _notify_admin_event("[ADMIN] Nouveau professionnel ajouté", f"Pro: {professional.name} (id {professional.id}) — statut en_attente")
        return redirect(url_for('admin.admin_products'))

    return render_template('add_product.html')

@admin_bp.route('/products/edit/<int:product_id>', methods=['GET', 'POST'], endpoint='admin_edit_product')
@login_required
def admin_edit_product(product_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    professional = Professional.query.get_or_404(product_id)

    if request.method == 'POST':
        # Champs basiques
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()
        professional.specialty = (request.form.get('specialty') or request.form.get('category') or professional.specialty).strip()
        professional.image_url = (request.form.get('image_url') or professional.image_url or '').strip()
        _u2 = (request.form.get('image_url2') or '').strip()
_u3 = (request.form.get('image_url3') or '').strip()
if _u2 != '':
    professional.image_url2 = _u2
if _u3 != '':
    professional.image_url3 = _u3

        professional.location = (request.form.get('location') or professional.location or '').strip()
        professional.phone = (request.form.get('phone') or professional.phone or '').strip()

        # Tarif
        fee_raw = (request.form.get('consultation_fee') or request.form.get('price') or '').replace(',', '.')
        if fee_raw:
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Tarif invalide.", "error")

        # Expérience
        exp_raw = (request.form.get('experience_years') or request.form.get('experience') or '').strip()
        if exp_raw != '':
            try:
                professional.experience_years = max(0, int(exp_raw))
            except ValueError:
                flash("Années d'expérience invalide.", "error")

        # Adresse / géoloc
        professional.address = (request.form.get('address') or '').strip() or None
        lat_raw = (request.form.get('latitude') or '').strip()
        lng_raw = (request.form.get('longitude') or '').strip()
        try:
            professional.latitude = float(lat_raw) if lat_raw else professional.latitude
        except ValueError:
            flash("Latitude invalide", "error")
        try:
            professional.longitude = float(lng_raw) if lng_raw else professional.longitude
        except ValueError:
            flash("Longitude invalide", "error")

        # Statut & disponibilité
        status_val = (request.form.get('status') or '').strip()
        if status_val in ('valide', 'en_attente', 'rejete'):
            professional.status = status_val

        # disponibilité (compat stock)
        stock = request.form.get('stock')
        if stock is not None:
            professional.availability = 'disponible' if stock in ('1', 'true', 'on', 'yes') else 'indisponible'
        else:
            availability = request.form.get('availability')
            if availability:
                professional.availability = availability

        # Types de consultation
        types_list = request.form.getlist('consultation_types')
        if types_list or any(request.form.get(k) for k in ['home_consultation', 'office_consultation', 'online_consultation']):
            t = []
            if request.form.get('home_consultation'): t.append('domicile')
            if request.form.get('office_consultation'): t.append('cabinet')
            if request.form.get('online_consultation'): t.append('en_ligne')
            if not t and types_list:
                t = types_list
            if t:
                professional.consultation_types = ','.join(t)

        # Badges + mise en avant
        professional.certified_tighri   = bool(request.form.get('certified_tighri'))
        professional.approved_anthecc   = bool(request.form.get('approved_anthecc'))
        is_featured_val = (request.form.get('is_featured') or '').lower()
        professional.is_featured = True if is_featured_val in ('on', '1', 'true', 'yes') else False
        fr_raw = (request.form.get('featured_rank') or '').strip()
        professional.featured_rank = int(fr_raw) if fr_raw.isdigit() else None

        # Réseaux sociaux
        professional.facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        professional.instagram_url = (request.form.get('instagram_url') or '').strip() or None
        professional.tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        professional.youtube_url   = (request.form.get('youtube_url')   or '').strip() or None
        professional.social_links_approved = bool(request.form.get('social_links_approved'))

        # durée/buffer
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        if dur_raw:
            try:
                professional.consultation_duration_minutes = max(5, min(240, int(dur_raw)))
            except ValueError:
                flash("Durée invalide (minutes).", "error")
        if buf_raw:
            try:
                professional.buffer_between_appointments_minutes = max(0, min(120, int(buf_raw)))
            except ValueError:
                flash("Buffer invalide (minutes).", "error")

        # upload fichier image (optionnel)
        file = request.files.get('image_file')
        if file and getattr(file, 'filename', ''):
            try:
                saved = _admin_process_and_save_profile_image(file)
                professional.image_url = f"/media/profiles/{saved}"
            except Exception as e:
                flash(f"Image non enregistrée ({e}).", "warning")
file2 = request.files.get('image_file2')
if file2 and getattr(file2, 'filename', ''):
    try:
        saved2 = _admin_process_and_save_profile_image(file2)
        professional.image_url2 = f"/media/profiles/{saved2}"
    except Exception as e:
        flash(f"Image 2 non enregistrée ({e}).", "warning")

file3 = request.files.get('image_file3')
if file3 and getattr(file3, 'filename', ''):
    try:
        saved3 = _admin_process_and_save_profile_image(file3)
        professional.image_url3 = f"/media/profiles/{saved3}"
    except Exception as e:
        flash(f"Image 3 non enregistrée ({e}).", "warning")

        db.session.commit()
        flash('Professionnel modifié avec succès!')
        _notify_admin_event("[ADMIN] Profil pro mis à jour", f"Pro: {professional.name} (id {professional.id})")
        return redirect(url_for('admin.admin_products'))

    return render_template('edit_product.html', professional=professional)

@admin_bp.route('/products/<int:product_id>/delete', methods=['POST'], endpoint='admin_delete_product')
@login_required
def admin_delete_product(product_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    professional = Professional.query.get_or_404(product_id)
    db.session.delete(professional)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Professionnel supprimé avec succès'})

# Variante CRUD /professionals
@admin_bp.route('/professionals', endpoint='admin_professionals')
@login_required
def admin_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    professionals = Professional.query.order_by(Professional.id.desc()).all()
    return render_template('admin_professionals.html', professionals=professionals)

@admin_bp.route('/professionals/edit/<int:professional_id>', methods=['GET', 'POST'], endpoint='edit_professional')
@login_required
def edit_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    professional = Professional.query.get_or_404(professional_id)

    if request.method == 'POST':
        # Champs basiques
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()
        professional.specialty = (request.form.get('specialty') or request.form.get('category') or professional.specialty).strip()
        professional.image_url = (request.form.get('image_url') or professional.image_url or '').strip()

        # Tarif
        fee_raw = (request.form.get('consultation_fee') or request.form.get('price') or '').replace(',', '.').strip()
        if fee_raw != '':
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Le tarif est invalide.", "error")
                return redirect(url_for('admin.edit_professional', professional_id=professional_id))

        # Expérience
        exp_raw = (request.form.get('experience_years') or request.form.get('experience') or '').strip()
        if exp_raw != '':
            try:
                professional.experience_years = max(0, int(exp_raw))
            except ValueError:
                flash("Années d'expérience invalide.", "error")
                return redirect(url_for('admin.edit_professional', professional_id=professional_id))

        # Statut
        status = (request.form.get('status') or '').strip()
        if status in ('valide', 'en_attente', 'rejete'):
            professional.status = status

        # Téléphone / Adresse / Ville
        professional.phone = (request.form.get('phone') or professional.phone or '').strip() or None
        professional.location = (request.form.get('location') or professional.location or '').strip()
        professional.address = (request.form.get('address') or professional.address or '').strip() or None

        lat_raw = (request.form.get('latitude') or '').strip()
        lng_raw = (request.form.get('longitude') or '').strip()
        try:
            professional.latitude = float(lat_raw) if lat_raw else professional.latitude
        except ValueError:
            flash("Latitude invalide", "error")
        try:
            professional.longitude = float(lng_raw) if lng_raw else professional.longitude
        except ValueError:
            flash("Longitude invalide", "error")

        # Disponibilité
        availability = (request.form.get('availability') or '').strip()
        if availability in ('disponible', 'indisponible'):
            professional.availability = availability

        # Types de consultation (checkboxes multiples)
        types_list = request.form.getlist('consultation_types')
        if types_list:
            professional.consultation_types = ','.join(types_list)

        # Badges + mise en avant
        professional.certified_tighri   = bool(request.form.get('certified_tighri'))
        professional.approved_anthecc   = bool(request.form.get('approved_anthecc'))
        is_featured_val = (request.form.get('is_featured') or '').lower()
        professional.is_featured = True if is_featured_val in ('on', '1', 'true', 'yes') else False
        fr_raw = (request.form.get('featured_rank') or '').strip()
        professional.featured_rank = int(fr_raw) if fr_raw.isdigit() else None

        # Réseaux sociaux
        professional.facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        professional.instagram_url = (request.form.get('instagram_url') or '').strip() or None
        professional.tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        professional.youtube_url   = (request.form.get('youtube_url')   or '').strip() or None
        professional.social_links_approved = bool(request.form.get('social_links_approved'))

        # durée/buffer
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        if dur_raw:
            try:
                professional.consultation_duration_minutes = max(5, min(240, int(dur_raw)))
            except ValueError:
                flash("Durée invalide (minutes).", "error")
        if buf_raw:
            try:
                professional.buffer_between_appointments_minutes = max(0, min(120, int(buf_raw)))
            except ValueError:
                flash("Buffer invalide (minutes).", "error")

        # upload image (optionnel)
        file = request.files.get('image_file')
        if file and getattr(file, 'filename', ''):
            try:
                saved = _admin_process_and_save_profile_image(file)
                professional.image_url = f"/media/profiles/{saved}"
            except Exception as e:
                flash(f"Image non enregistrée ({e}).", "warning")

        db.session.commit()
        flash('Professionnel modifié avec succès!')
        _notify_admin_event("[ADMIN] Profil pro modifié (route edit_professional)", f"Pro: {professional.name} (id {professional.id})")
        return redirect(url_for('admin.admin_professionals'))

    return render_template('edit_product.html', professional=professional)

@admin_bp.route('/professionals/delete/<int:professional_id>', methods=['GET', 'POST'], endpoint='delete_professional')
@login_required
def delete_professional(professional_id):
    if not current_user.is_admin:
        if request.method == 'POST' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Accès refusé'}), 403
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    professional = Professional.query.get_or_404(professional_id)
    db.session.delete(professional)
    db.session.commit()

    # Réponse selon le contexte (XHR vs navigation)
    if request.method == 'POST' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Professionnel supprimé avec succès'})
    flash('Professionnel supprimé avec succès!')
    return redirect(url_for('admin.admin_professionals'))

@admin_bp.route('/professionals/<int:professional_id>', endpoint='view_professional')
@login_required
def view_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    professional = Professional.query.get_or_404(professional_id)
    appointments = Appointment.query.filter_by(professional_id=professional_id).order_by(Appointment.appointment_date.desc()).all()
    return render_template('view_professional.html', professional=professional, appointments=appointments)

# ---------- Gestion des disponibilités (ADMIN) ----------
@admin_bp.route('/professionals/<int:professional_id>/availability', methods=['GET', 'POST'], endpoint='admin_professional_availability')
@login_required
def admin_professional_availability(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    professional = Professional.query.get_or_404(professional_id)

    if request.method == 'POST':
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        def add_window(day, s, e, avail_flag):
            s = (s or '').strip()
            e = (e or '').strip()
            if avail_flag and s and e:
                av = ProfessionalAvailability(
                    professional_id=professional.id,
                    day_of_week=day,
                    start_time=s,
                    end_time=e,
                    is_available=True
                )
                db.session.add(av)

        for day in range(7):
            base_flag = request.form.get(f'available_{day}') == 'on'
            add_window(day, request.form.get(f'start_time_{day}', ''), request.form.get(f'end_time_{day}', ''), base_flag)
            add_window(day, request.form.get(f'start_time_{day}_2', ''), request.form.get(f'end_time_{day}_2', ''), request.form.get(f'available_{day}_2') == 'on' or base_flag)
            add_window(day, request.form.get(f'start_time_{day}_3', ''), request.form.get(f'end_time_{day}_3', ''), request.form.get(f'available_{day}_3') == 'on' or base_flag)

        db.session.commit()
        flash('Disponibilités mises à jour !')
        return redirect(url_for('admin.admin_professional_availability', professional_id=professional.id))

    all_avs = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    windows_by_day = {d: [] for d in range(7)}
    for av in all_avs:
        windows_by_day.get(av.day_of_week, []).append(av)
    availability_dict = {d: (windows_by_day[d][0] if windows_by_day[d] else None) for d in range(7)}

    return render_template('admin_professional_availability.html',
                           professional=professional,
                           availabilities=availability_dict,
                           windows_by_day=windows_by_day)

# ---------- Gestion des indisponibilités (ADMIN) ----------
@admin_bp.route('/professionals/<int:professional_id>/unavailable-slots', methods=['GET', 'POST'], endpoint='admin_professional_unavailable_slots')
@login_required
def admin_professional_unavailable_slots(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé'); return redirect(url_for('admin.admin_login'))

    professional = Professional.query.get_or_404(professional_id)

    if request.method == 'POST':
        date_str = request.form.get('date', '')
        start_time = request.form.get('start_time', '')
        end_time = request.form.get('end_time', '')
        reason = request.form.get('reason', '').strip()

        try:
            slot_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Format de date invalide'); return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional.id))

        if slot_date < date.today():
            flash('Impossible de bloquer une date passée'); return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional.id))

        if not start_time or not end_time:
            flash("Heure de début et de fin obligatoires."); return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional.id))

        slot = UnavailableSlot(
            professional_id=professional.id,
            date=slot_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason
        )
        db.session.add(slot)
        db.session.commit()
        flash('Créneau indisponible ajouté.')
        return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional.id))

    unavailable_slots = UnavailableSlot.query.filter_by(professional_id=professional.id) \
                                             .order_by(UnavailableSlot.date.desc()) \
                                             .all()
    return render_template('admin_professional_unavailable_slots.html',
                           professional=professional,
                           unavailable_slots=unavailable_slots)

@admin_bp.route('/professionals/<int:professional_id>/unavailable-slots/<int:slot_id>/delete', methods=['POST'], endpoint='admin_delete_unavailable_slot')
@login_required
def admin_delete_unavailable_slot(professional_id, slot_id):
    if not current_user.is_admin:
        flash('Accès refusé'); return redirect(url_for('admin.admin_login'))
    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional_id:
        flash('Accès refusé'); return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional_id))
    db.session.delete(slot)
    db.session.commit()
    flash('Créneau supprimé.')
    return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional_id))

# --------------------- UTILISATEURS ---------------------
def _get_or_create_archived_user():
    placeholder_username = "[deleted]"
    placeholder_email = "deleted@tighri.local"

    u = User.query.filter_by(username=placeholder_username).first()
    if not u:
        u = User.query.filter_by(email=placeholder_email).first()

    if not u:
        pw = generate_password_hash(uuid.uuid4().hex)
        u = User(
            username=placeholder_username,
            email=placeholder_email,
            password_hash=pw,
            user_type="patient",
            is_admin=False,
            phone=None,
        )
        db.session.add(u)
        db.session.flush()
    return u

@admin_bp.route('/users', endpoint='admin_users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    users = User.query.order_by(User.id.desc()).all()
    return render_template('admin_users.html', users=users)

@admin_bp.route('/users/add', methods=['GET', 'POST'], endpoint='add_user')
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = (request.form.get('password') or '')
        user_type = (request.form.get('user_type') or 'patient').strip()
        is_admin = 'is_admin' in request.form
        phone = (request.form.get('phone') or '').strip()

        if not username or not email or not password:
            flash("Tous les champs sont obligatoires")
            return redirect(url_for('admin.add_user'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà utilisé")
            return redirect(url_for('admin.add_user'))
        if User.query.filter_by(email=email).first():
            flash("Email déjà utilisé")
            return redirect(url_for('admin.add_user'))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type=user_type,
            is_admin=bool(is_admin),
            phone=phone or None
        )
        db.session.add(user)
        db.session.commit()
        flash('Utilisateur ajouté avec succès!')

        _notify_user_account(user.email, "account_created")
        _notify_admin_event("[ADMIN] Compte créé", f"User: {user.username} ({user.email}) — type={user.user_type}, admin={user.is_admin}")

        return redirect(url_for('admin.admin_users'))

    return render_template('add_user.html')

@admin_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'], endpoint='edit_user')
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        old_username = user.username

        username = (request.form.get('username') or user.username).strip()
        email = (request.form.get('email') or user.email).strip().lower()
        user_type = (request.form.get('user_type') or user.user_type).strip()
        is_admin = 'is_admin' in request.form
        new_pw = (request.form.get('new_password') or request.form.get('password') or '').strip()
        phone = (request.form.get('phone') or user.phone or '').strip()

        if User.query.filter(User.username == username, User.id != user.id).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('admin.edit_user', user_id=user.id))
        if User.query.filter(User.email == email, User.id != user.id).first():
            flash("Email déjà enregistré")
            return redirect(url_for('admin.edit_user', user_id=user.id))

        user.username = username
        user.email = email
        user.user_type = user_type
        user.is_admin = bool(is_admin)
        user.phone = phone or None
        if new_pw:
            user.password_hash = generate_password_hash(new_pw)

        try:
            if user_type == 'professional':
                pro = Professional.query.filter_by(name=username).first()
                if not pro:
                    pro_old = Professional.query.filter_by(name=old_username).first()
                    if pro_old and old_username != username:
                        pro_old.name = username
                        pro = pro_old
                if not pro:
                    pro = Professional(
                        name=username,
                        description="Profil en cours de complétion.",
                        specialty="Psychologue",
                        location="Casablanca",
                        experience_years=0,
                        consultation_fee=0.0,
                        phone=user.phone or None,
                        status="en_attente"
                    )
                    db.session.add(pro)
        except Exception as e:
            flash(f"Attention: la synchronisation du profil professionnel a rencontré un souci: {e}", "warning")

        db.session.commit()
        flash('Utilisateur modifié avec succès!')

        _notify_user_account(user.email, "account_updated")
        _notify_admin_event("[ADMIN] Compte modifié", f"User: {user.username} ({user.email}) — type={user.user_type}, admin={user.is_admin}")

        return redirect(url_for('admin.admin_users'))

    # Pour pré-remplir la section pro dans le template (si tu l'utilises)
    pro = Professional.query.filter_by(name=user.username).first()
    return render_template('edit_user.html', user=user, pro=pro)

@admin_bp.route('/users/delete/<int:user_id>', methods=['GET', 'POST'], endpoint='delete_user')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    user = User.query.get_or_404(user_id)

    try:
        archived = _get_or_create_archived_user()
        db.session.query(Appointment).filter_by(patient_id=user.id).update(
            {Appointment.patient_id: archived.id},
            synchronize_session=False
        )

        db.session.delete(user)
        db.session.commit()
        flash('Utilisateur supprimé avec succès!')
        _notify_admin_event("[ADMIN] Compte supprimé", f"User id {user_id} supprimé. RDV réassignés à [deleted].")
    except Exception as e:
        db.session.rollback()
        flash(f'Erreur lors de la suppression: {e}', 'error')

    return redirect(url_for('admin.admin_users'))

# --------------------- RDV / COMMANDES ---------------------
@admin_bp.route('/appointments', endpoint='admin_appointments')
@login_required
def admin_appointments():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    appointments = Appointment.query.order_by(Appointment.appointment_date.desc()).all()
    return render_template('admin_appointments.html', appointments=appointments)

@admin_bp.route('/orders', endpoint='admin_orders')
@login_required
def admin_orders():
    return redirect(url_for('admin.admin_appointments'))

# ===== Changement de statut RDV =====
@admin_bp.route('/orders/<int:appointment_id>/status', methods=['POST'], endpoint='update_appointment_status')
@login_required
def update_appointment_status(appointment_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    try:
        data = request.get_json(silent=True) or {}
        new_status = data.get('status')
        if new_status not in ['confirme', 'en_attente', 'annule']:
            return jsonify({'success': False, 'message': 'Statut invalide'}), 400
        appointment = Appointment.query.get_or_404(appointment_id)
        appointment.status = new_status
        db.session.commit()

        if new_status == 'confirme':
            _notify_patient('accepted', appointment)
            _notify_pro('accepted', appointment)
            _notify_admin_for_appointment('accepted', appointment)
        elif new_status == 'annule':
            _notify_patient('refused', appointment)
            _notify_pro('refused', appointment)
            _notify_admin_for_appointment('refused', appointment)
        elif new_status == 'en_attente':
            _notify_patient('pending', appointment)
            _notify_pro('pending', appointment)
            _notify_admin_for_appointment('pending', appointment)

        return jsonify({'success': True, 'message': f'Rendez-vous {new_status}'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# --------------------- API STATS & VALIDATION PRO ---------------------
@admin_bp.route('/api/stats', endpoint='api_stats')
@login_required
def api_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Accès refusé'}), 403
    professionals = Professional.query.all()
    users = User.query.all()
    appointments = Appointment.query.all()
    stats = {
        'total_professionals': len(professionals),
        'total_users': len(users),
        'total_appointments': len(appointments),
        'confirmed_appointments': len([a for a in appointments if a.status == 'confirme']),
        'pending_appointments': len([a for a in appointments if a.status == 'en_attente'])
    }
    return jsonify(stats)

@admin_bp.route('/professionals/<int:professional_id>/validate', methods=['POST'], endpoint='validate_professional')
@login_required
def validate_professional(professional_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    try:
        professional = Professional.query.get_or_404(professional_id)
        professional.status = 'valide'
        db.session.commit()

        pro_user = User.query.filter_by(username=professional.name).first()
        _notify_user_account(getattr(pro_user, 'email', None), "pro_validated", pro=professional)
        _notify_admin_event("[ADMIN] Pro validé", f"Pro: {professional.name} (id {professional.id})")

        return jsonify({'success': True, 'message': 'Professionnel validé avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/professionals/<int:professional_id>/reject', methods=['POST'], endpoint='reject_professional')
@login_required
def reject_professional(professional_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    try:
        professional = Professional.query.get_or_404(professional_id)
        professional.status = 'rejete'
        db.session.commit()

        pro_user = User.query.filter_by(username=professional.name).first()
        _notify_user_account(getattr(pro_user, 'email', None), "pro_rejected", pro=professional)
        _notify_admin_event("[ADMIN] Pro rejeté", f"Pro: {professional.name} (id {professional.id})")

        return jsonify({'success': True, 'message': 'Professionnel rejeté'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/pending-professionals', endpoint='pending_professionals')
@login_required
def pending_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    pending_professionals = Professional.query.filter_by(status='en_attente').all()
    return render_template('pending_professionals.html', professionals=pending_professionals)

@admin_bp.route('/professionals/<int:professional_id>/social-approval', methods=['POST'], endpoint='social_approval')
@login_required
def social_approval(professional_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    professional = Professional.query.get_or_404(professional_id)
    data = request.get_json(silent=True) or {}
    approved = bool(data.get('approved', False))
    if hasattr(professional, 'social_links_approved'):
        professional.social_links_approved = approved
        db.session.commit()

        pro_user = User.query.filter_by(username=professional.name).first()
        _notify_user_account(getattr(pro_user, 'email', None),
                             "social_links_approved" if approved else "social_links_unapproved",
                             pro=professional)
        _notify_admin_event("[ADMIN] Social links " + ("approuvés" if approved else "désapprouvés"),
                            f"Pro: {professional.name} (id {professional.id}) — approved={approved}")

        return jsonify({'success': True, 'approved': approved})
    return jsonify({'success': False, 'message': 'Champ social_links_approved non disponible'}), 400
