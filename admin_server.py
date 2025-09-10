# admin_server.py
from functools import wraps
from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort, send_file
)
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from sqlalchemy import func
from io import BytesIO

from models import (
    db, User, Professional, Appointment,
    ProfessionalOrder, ProfessionalAvailabilityWindow, ProfessionalUnavailableSlot,
    Review, SocialLink
)

admin_bp = Blueprint('admin', __name__, url_prefix='/admin', template_folder='templates')

# -------- Helpers
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('admin.admin_login', next=request.full_path))
        if not getattr(current_user, 'is_admin', False):
            flash("Accès administrateur requis.", "error")
            return redirect(url_for('admin.admin_login', next=request.full_path))
        return fn(*args, **kwargs)
    return wrapper

# -------- Auth
@admin_bp.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = User.query.filter((User.username == username) | (User.email == username)).first()
        if user and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user, remember=bool(request.form.get('remember')))
            nxt = request.form.get('next') or request.args.get('next') or url_for('admin.admin_dashboard')
            return redirect(nxt)
        flash("Identifiants invalides ou droits insuffisants.", "error")
    return render_template('admin_login.html')

@admin_bp.route('/logout')
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for('admin.admin_login'))

# -------- Dashboard
@admin_bp.route('/')
@admin_required
def admin_dashboard():
    total_professionals = db.session.scalar(db.select(func.count(Professional.id))) or 0
    total_users = db.session.scalar(db.select(func.count(User.id))) or 0
    total_appointments = db.session.scalar(db.select(func.count(Appointment.id))) or 0

    professionals = db.session.execute(
        db.select(Professional).order_by(Professional.id.desc()).limit(20)
    ).scalars().all()
    appointments = db.session.execute(
        db.select(Appointment).order_by(Appointment.id.desc()).limit(20)
    ).scalars().all()
    users = db.session.execute(
        db.select(User).order_by(User.id.desc()).limit(20)
    ).scalars().all()

    # estimation revenu (optionnelle)
    total_revenue = db.session.scalar(db.select(func.coalesce(func.sum(Professional.consultation_fee), 0.0)))

    return render_template(
        'admin_dashboard.html',
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        professionals=professionals,
        appointments=appointments,
        users=users,
        total_revenue=total_revenue or 0
    )

# -------- Classement professionnels
@admin_bp.route('/professional-order', methods=['GET', 'POST'])
@admin_required
def admin_professional_order():
    if request.method == 'POST':
        pros = db.session.execute(db.select(Professional)).scalars().all()
        for p in pros:
            key = f'order_priority_{p.id}'
            if key in request.form:
                try:
                    val = int(request.form[key])
                except Exception:
                    val = 9999
                entry = db.session.get(ProfessionalOrder, p.id)
                if not entry:
                    db.session.add(ProfessionalOrder(professional_id=p.id, order_priority=val))
                else:
                    entry.order_priority = val
        db.session.commit()
        flash("Classement mis à jour.", "success")
        return redirect(url_for('admin.admin_professional_order'))

    professionals = db.session.execute(
        db.select(Professional).order_by(Professional.name.asc())
    ).scalars().all()
    orders = {o.professional_id: o.order_priority for o in db.session.execute(
        db.select(ProfessionalOrder)
    ).scalars()}
    return render_template('admin_professional_order.html', professionals=professionals, orders=orders)

# -------- Professionnels (listes / CRUD minimal)
@admin_bp.route('/professionals')
@admin_required
def admin_products():
    pros = db.session.execute(
        db.select(Professional).order_by(Professional.id.desc())
    ).scalars().all()
    return render_template('admin_products.html', professionals=pros)

@admin_bp.route('/professionals/pending')
@admin_required
def pending_professionals():
    pros = db.session.execute(
        db.select(Professional).where(Professional.status == 'en_attente').order_by(Professional.id.desc())
    ).scalars().all()
    return render_template('pending_professionals.html', professionals=pros)

@admin_bp.route('/professionals/<int:professional_id>')
@admin_required
def view_professional(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)
    appts = db.session.execute(
        db.select(Appointment).where(Appointment.professional_id == professional_id).order_by(Appointment.id.desc()).limit(50)
    ).scalars().all()
    return render_template('view_professional.html', professional=p, appointments=appts)

@admin_bp.route('/professionals/<int:professional_id>/availability', methods=['GET', 'POST'])
@admin_required
def admin_professional_availability(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)

    if request.method == 'POST':
        # On remplace simplement les fenêtres existantes par la nouvelle saisie (simple et safe)
        db.session.query(ProfessionalAvailabilityWindow).filter_by(professional_id=p.id).delete()
        for d in range(7):
            for suffix in ['', '_2', '_3']:
                active = bool(request.form.get(f'available_{d}{suffix}'))
                st = request.form.get(f'start_time_{d}{suffix}') or ''
                et = request.form.get(f'end_time_{d}{suffix}') or ''
                if active and st and et:
                    db.session.add(ProfessionalAvailabilityWindow(
                        professional_id=p.id, weekday=d, start_time=st, end_time=et
                    ))
        db.session.commit()
        flash("Disponibilités mises à jour.", "success")
        return redirect(url_for('admin.admin_professional_availability', professional_id=p.id))

    # GET
    windows_by_day = {d: [] for d in range(7)}
    for w in p.availability_windows:
        windows_by_day[w.weekday].append(w)
    # tri par début
    for d in windows_by_day:
        windows_by_day[d] = sorted(windows_by_day[d], key=lambda x: x.start_time or '')
    return render_template('admin_professional_availability.html', professional=p, windows_by_day=windows_by_day)

@admin_bp.route('/professionals/<int:professional_id>/unavailable-slots', methods=['GET', 'POST'])
@admin_required
def admin_professional_unavailable_slots(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)

    if request.method == 'POST':
        try:
            date_str = request.form.get('date')
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            reason = request.form.get('reason')
            if not (date_str and start_time and end_time):
                raise ValueError("Champs requis manquants.")
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            db.session.add(ProfessionalUnavailableSlot(
                professional_id=p.id, date=dt, start_time=start_time, end_time=end_time, reason=reason
            ))
            db.session.commit()
            flash("Indisponibilité ajoutée.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur: {e}", "error")
        return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=p.id))

    slots = db.session.execute(
        db.select(ProfessionalUnavailableSlot).where(ProfessionalUnavailableSlot.professional_id == p.id).order_by(
            ProfessionalUnavailableSlot.date.desc(), ProfessionalUnavailableSlot.start_time.asc()
        )
    ).scalars().all()
    return render_template('admin_professional_unavailable_slots.html', professional=p, unavailable_slots=slots)

@admin_bp.route('/professionals/<int:professional_id>/unavailable-slots/<int:slot_id>/delete', methods=['POST'])
@admin_required
def admin_delete_unavailable_slot(professional_id, slot_id):
    slot = db.session.get(ProfessionalUnavailableSlot, slot_id) or abort(404)
    db.session.delete(slot)
    db.session.commit()
    flash("Indisponibilité supprimée.", "success")
    return redirect(url_for('admin.admin_professional_unavailable_slots', professional_id=professional_id))

@admin_bp.route('/professionals/add', methods=['GET', 'POST'])
@admin_required
def admin_add_product():
    if request.method == 'POST':
        p = Professional(
            name=request.form.get('name') or '',
            specialty=request.form.get('specialty'),
            location=request.form.get('location'),
            phone=request.form.get('phone'),
            address=request.form.get('address'),
            latitude=request.form.get('latitude'),
            longitude=request.form.get('longitude'),
            consultation_fee=(float(request.form.get('consultation_fee') or 0) or None),
            consultation_duration_minutes=int(request.form.get('consultation_duration_minutes') or 45),
            buffer_between_appointments_minutes=int(request.form.get('buffer_between_appointments_minutes') or 15),
            experience_years=int(request.form.get('experience_years') or 0),
            description=request.form.get('description'),
            image_url=request.form.get('image_url'),
            availability=request.form.get('availability') or 'disponible',
            consultation_types=",".join(request.form.getlist('consultation_types')),
            facebook_url=request.form.get('facebook_url'),
            instagram_url=request.form.get('instagram_url'),
            tiktok_url=request.form.get('tiktok_url'),
            youtube_url=request.form.get('youtube_url'),
            social_links_approved=bool(request.form.get('social_links_approved'))
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel ajouté.", "success")
        return redirect(url_for('admin.admin_products'))
    return render_template('add_product.html')

@admin_bp.route('/professionals/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_product(product_id):
    p = db.session.get(Professional, product_id) or abort(404)
    if request.method == 'POST':
        # Mise à jour minimale (compat avec ton template)
        p.name = request.form.get('name') or p.name
        p.specialty = request.form.get('specialty')
        p.location = request.form.get('location')
        p.phone = request.form.get('phone')
        p.address = request.form.get('address')
        p.latitude = request.form.get('latitude')
        p.longitude = request.form.get('longitude')
        p.consultation_fee = float(request.form.get('consultation_fee') or 0) or None
        p.consultation_duration_minutes = int(request.form.get('consultation_duration_minutes') or 45)
        p.buffer_between_appointments_minutes = int(request.form.get('buffer_between_appointments_minutes') or 15)
        p.experience_years = int(request.form.get('experience_years') or 0)
        p.description = request.form.get('description')
        new_image_url = request.form.get('image_url')
        if new_image_url:
            p.image_url = new_image_url
        p.consultation_types = ",".join(request.form.getlist('consultation_types'))
        p.availability = request.form.get('availability') or p.availability
        p.status = request.form.get('status') or p.status
        p.facebook_url = request.form.get('facebook_url')
        p.instagram_url = request.form.get('instagram_url')
        p.tiktok_url = request.form.get('tiktok_url')
        p.youtube_url = request.form.get('youtube_url')
        p.social_links_approved = bool(request.form.get('social_links_approved'))
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for('admin.view_professional', professional_id=p.id))
    return render_template('edit_product.html', professional=p)

# Actions simples attendues par certains JS des templates “pending”
@admin_bp.route('/professionals/<int:professional_id>/validate', methods=['POST'])
@admin_required
def validate_professional(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)
    p.status = 'valide'
    db.session.commit()
    return jsonify(success=True)

@admin_bp.route('/professionals/<int:professional_id>/reject', methods=['POST'])
@admin_required
def reject_professional(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)
    p.status = 'rejete'
    db.session.commit()
    return jsonify(success=True)

@admin_bp.route('/professionals/<int:professional_id>/delete')
@admin_required
def delete_professional(professional_id):
    p = db.session.get(Professional, professional_id) or abort(404)
    db.session.delete(p)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for('admin.admin_products'))

# -------- Utilisateurs
@admin_bp.route('/users')
@admin_required
def admin_users():
    users = db.session.execute(db.select(User).order_by(User.id.desc())).scalars().all()
    return render_template('admin_users.html', users=users)

@admin_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        u = User(
            username=request.form.get('username') or '',
            email=request.form.get('email') or '',
            password_hash=generate_password_hash(request.form.get('password') or ''),
            is_admin=bool(request.form.get('is_admin'))
        )
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur ajouté.", "success")
        return redirect(url_for('admin.admin_users'))
    return render_template('add_user.html')

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    u = db.session.get(User, user_id) or abort(404)
    if request.method == 'POST':
        u.username = request.form.get('username') or u.username
        u.email = request.form.get('email') or u.email
        u.phone = request.form.get('phone')
        if request.form.get('password'):
            u.password_hash = generate_password_hash(request.form.get('password'))
        u.is_admin = bool(request.form.get('is_admin'))
        # conversion rapide: si user_type == professional, on crée un pro minimal si besoin
        new_type = request.form.get('user_type') or u.user_type
        if new_type != u.user_type:
            u.user_type = new_type
            if new_type == 'professional':
                exists = db.session.execute(
                    db.select(Professional).where(Professional.phone == u.phone)
                ).scalar_one_or_none()
                if not exists:
                    pro = Professional(name=u.username or 'Professionnel', phone=u.phone)
                    db.session.add(pro)
        db.session.commit()
        flash("Utilisateur mis à jour.", "success")
        return redirect(url_for('admin.admin_users'))
    return render_template('edit_user.html', user=u)

@admin_bp.route('/users/<int:user_id>/delete')
@admin_required
def delete_user(user_id):
    u = db.session.get(User, user_id) or abort(404)
    db.session.delete(u)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for('admin.admin_users'))

# -------- Rendez-vous
@admin_bp.route('/appointments')
@admin_required
def admin_appointments():
    appointments = db.session.execute(
        db.select(Appointment).order_by(Appointment.id.desc())
    ).scalars().all()
    return render_template('admin_appointments.html', appointments=appointments)

@admin_bp.route('/appointments/<int:appointment_id>/status', methods=['POST'])
@admin_required
def update_appointment_status(appointment_id):
    ap = db.session.get(Appointment, appointment_id) or abort(404)
    status = (request.get_json(silent=True) or {}).get('status')
    if status not in ('en_attente', 'confirme', 'annule'):
        return jsonify(success=False, message='Statut invalide'), 400
    ap.status = status
    db.session.commit()
    return jsonify(success=True)

# Alias “orders” si tu utilises encore admin_orders.html pour une autre vue
@admin_bp.route('/orders')
@admin_required
def admin_orders():
    appointments = db.session.execute(
        db.select(Appointment).order_by(Appointment.id.desc())
    ).scalars().all()
    return render_template('admin_orders.html', appointments=appointments)

# -------- Avis & liens sociaux (pages “pending”)
@admin_bp.route('/reviews/pending')
@admin_required
def admin_reviews_pending():
    reviews = db.session.execute(
        db.select(Review).where(Review.approved.is_(False)).order_by(Review.id.desc())
    ).scalars().all()
    totals = db.session.execute(
        db.select(
            func.sum(func.case((Review.approved.is_(True), 1), else_=0)),
            func.sum(func.case((Review.approved.is_(False), 1), else_=0))
        )
    ).one()
    total_approved = totals[0] or 0
    total_rejected = 0  # si tu gères un flag "rejected" distinct, adapter ici
    return render_template('admin_reviews_pending.html', reviews=reviews,
                           total_approved=total_approved, total_rejected=total_rejected)

@admin_bp.route('/reviews/<int:review_id>/<string:action>', methods=['POST'])
@admin_required
def admin_reviews_action(review_id, action):
    r = db.session.get(Review, review_id) or abort(404)
    if action == 'approve':
        r.approved = True
        db.session.commit()
        flash("Avis approuvé.", "success")
    elif action == 'reject' or action == 'delete':
        db.session.delete(r)
        db.session.commit()
        flash("Avis supprimé.", "success")
    return redirect(url_for('admin.admin_reviews_pending'))

@admin_bp.route('/social/pending')
@admin_required
def admin_social_pending():
    links = db.session.execute(
        db.select(SocialLink).where(SocialLink.approved.is_(False)).order_by(SocialLink.id.desc())
    ).scalars().all()
    return render_template('admin_social_pending.html', links=links)

@admin_bp.route('/social/<int:link_id>/<string:action>', methods=['POST'])
@admin_required
def admin_social_action(link_id, action):
    l = db.session.get(SocialLink, link_id) or abort(404)
    if action == 'approve':
        l.approved = True
        db.session.commit()
        flash("Lien approuvé.", "success")
    elif action == 'reject':
        db.session.delete(l)
        db.session.commit()
        flash("Lien rejeté.", "success")
    return redirect(url_for('admin.admin_social_pending'))

# -------- Photo profil (utilisé par tes templates)
@admin_bp.route('/profile-photo/<int:professional_id>')
@admin_required
def profile_photo_admin(professional_id):
    """Route protégée /admin pour affichage; ton template public utilise peut-être une route publique /profile_photo.
       On renvoie un placeholder si pas d'URL/image stockée côté disque."""
    pro = db.session.get(Professional, professional_id) or abort(404)
    # si tu as un stockage fichier, adapte ici; sinon placeholder
    # on renvoie un petit PNG blanc (1x1) pour éviter des 404 dans l’admin
    png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82'
    return send_file(BytesIO(png), mimetype='image/png')
