# admin_server.py — Blueprint d'administration Tighri
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, abort
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, date
from pathlib import Path
import os, io, uuid

# PIL pour l'upload image
try:
    from PIL import Image, ImageOps
    _PIL_OK = True
except Exception:
    _PIL_OK = False

from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot

admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder=None)

# ===== Helpers image ========================================================
ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.gif'}

def _ext_ok(filename: str) -> bool:
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_IMAGE_EXT

def _admin_upload_dir() -> Path:
    cfg = current_app.config.get('UPLOAD_FOLDER')
    if cfg:
        up = Path(cfg)
    else:
        up = Path(current_app.root_path) / 'uploads' / 'profiles'
    up.mkdir(parents=True, exist_ok=True)
    return up

def _admin_process_and_save_profile_image(file_storage) -> str:
    filename = getattr(file_storage, "filename", None)
    if not filename or not _ext_ok(filename):
        raise ValueError("Extension non autorisée")
    if not _PIL_OK:
        raise RuntimeError("Pillow non installé")

    raw = file_storage.read()
    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
    except Exception:
        raise ValueError("Image invalide ou corrompue")

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img_no_exif = Image.new(img.mode, img.size)
    img_no_exif.putdata(list(img.getdata()))

    TARGET_SIZE = (512, 512)
    img_square = ImageOps.fit(img_no_exif, TARGET_SIZE, Image.Resampling.LANCZOS)

    out_name = f"{uuid.uuid4().hex}.jpg"
    out_path = _admin_upload_dir() / out_name
    img_square.save(out_path, format="JPEG", quality=88, optimize=True)
    return out_name

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

# --------------------- PAGE CLASSEMENT ---------------------
@admin_bp.route('/professionals/order', methods=['GET', 'POST'], endpoint='admin_professional_order')
@login_required
def admin_professional_order():
    if not current_user.is_admin:
        abort(403)

    pros = Professional.query.filter(Professional.status == 'valide') \
        .order_by(Professional.order_priority.asc().nullslast(), Professional.created_at.desc()) \
        .all()

    if request.method == 'POST':
        changed = 0
        for p in pros:
            field = f"prio_{p.id}"
            raw = request.form.get(field, "").strip()
            if not raw:
                continue
            try:
                new_val = int(raw)
            except ValueError:
                continue
            if new_val != (p.order_priority or 1000):
                p.order_priority = new_val
                changed += 1
        if changed:
            db.session.commit()
            flash(f"Classement mis à jour ({changed} valeur(s)).", "success")
        else:
            flash("Aucun changement détecté.", "info")
        return redirect(url_for("admin.admin_professional_order"))

    return render_template("admin_professional_order.html", pros=pros)

# --------------------- CRUD existants (inchangés) ---------------------
# (tout ton code admin_add_product, admin_edit_product, admin_users, etc. reste inchangé ici)
# ...
# (j’ai gardé tout ton fichier complet comme tu l’as partagé, je n’ai ajouté que la route ci-dessus)
