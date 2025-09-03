# admin_server.py — Blueprint d'administration Tighri (une seule instance Flask dans app.py)
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, User, Professional, Appointment

admin_bp = Blueprint('admin', __name__, template_folder='templates', static_folder=None)

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
        phone = (request.form.get('phone') or '').strip()

        address = (request.form.get('address') or '').strip()
        lat_raw = (request.form.get('latitude') or '').strip()
        lng_raw = (request.form.get('longitude') or '').strip()
        try:
            latitude = float(lat_raw) if lat_raw else None
        except ValueError:
            latitude = None
            flash("Latitude invalide", "error")
        try:
            longitude = float(lng_raw) if lng_raw else None
        except ValueError:
            longitude = None
            flash("Longitude invalide", "error")

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

        # ✅ Durée & buffer (défauts 45/15 si rien)
        dur_raw = (request.form.get('consultation_duration_minutes') or '45').strip()
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '15').strip()
        try:
            consultation_duration_minutes = max(5, min(240, int(dur_raw)))
        except ValueError:
            consultation_duration_minutes = 45
        try:
            buffer_between_appointments_minutes = max(0, min(120, int(buf_raw)))
        except ValueError:
            buffer_between_appointments_minutes = 15

        if not name or not description or not specialty:
            flash("Nom, description et spécialité sont obligatoires.", "error")
            return redirect(url_for('admin.admin_add_product'))

        professional = Professional(
            name=name,
            description=description,
            consultation_fee=consultation_fee,
            image_url=image_url,
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
            # ✅ nouveaux champs
            consultation_duration_minutes=consultation_duration_minutes,
            buffer_between_appointments_minutes=buffer_between_appointments_minutes
        )
        db.session.add(professional)
        db.session.commit()
        flash('Professionnel ajouté avec succès!')
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
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()

        fee_raw = (request.form.get('consultation_fee') or request.form.get('price') or '').replace(',', '.')
        if fee_raw:
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Tarif invalide.", "error")

        professional.specialty = (request.form.get('specialty') or request.form.get('category') or professional.specialty).strip()
        professional.image_url = (request.form.get('image_url') or professional.image_url or '').strip()
        professional.location = (request.form.get('location') or professional.location or '').strip()
        professional.phone = (request.form.get('phone') or professional.phone or '').strip()

        address = (request.form.get('address') or '').strip()
        lat_raw = (request.form.get('latitude') or '').strip()
        lng_raw = (request.form.get('longitude') or '').strip()
        try:
            latitude = float(lat_raw) if lat_raw else getattr(professional, 'latitude', None)
        except ValueError:
            latitude = getattr(professional, 'latitude', None)
            flash("Latitude invalide", "error")
        try:
            longitude = float(lng_raw) if lng_raw else getattr(professional, 'longitude', None)
        except ValueError:
            longitude = getattr(professional, 'longitude', None)
            flash("Longitude invalide", "error")

        professional.address = address or None
        professional.latitude = latitude
        professional.longitude = longitude

        status_val = (request.form.get('status') or '').strip()
        if status_val:
            professional.status = status_val

        stock = request.form.get('stock')
        if stock is not None:
            professional.availability = 'disponible' if stock in ('1', 'true', 'on', 'yes') else 'indisponible'
        else:
            availability = request.form.get('availability')
            if availability:
                professional.availability = availability

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

        # Réseaux sociaux
        professional.facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        professional.instagram_url = (request.form.get('instagram_url') or '').strip() or None
        professional.tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        professional.youtube_url   = (request.form.get('youtube_url')   or '').strip() or None
        professional.social_links_approved = bool(request.form.get('social_links_approved'))

        exp_raw = request.form.get('experience_years')
        if exp_raw:
            try:
                professional.experience_years = int(exp_raw)
            except ValueError:
                flash("Expérience invalide", "error")

        # ✅ Durée & buffer (ne change que si fournis)
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        if dur_raw != '':
            try:
                professional.consultation_duration_minutes = max(5, min(240, int(dur_raw)))
            except ValueError:
                flash("Durée invalide (minutes).", "error")
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        if buf_raw != '':
            try:
                professional.buffer_between_appointments_minutes = max(0, min(120, int(buf_raw)))
            except ValueError:
                flash("Délai/buffer invalide (minutes).", "error")

        db.session.commit()
        flash('Professionnel modifié avec succès!')
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
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()
        professional.specialty = (request.form.get('specialty') or request.form.get('category') or professional.specialty).strip()
        professional.image_url = (request.form.get('image_url') or professional.image_url or '').strip()

        fee_raw = (request.form.get('consultation_fee') or request.form.get('price') or '').replace(',', '.').strip()
        if fee_raw != '':
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                flash("Le tarif est invalide.", "error")
                return redirect(url_for('admin.edit_professional', professional_id=professional_id))

        status = (request.form.get('status') or '').strip()
        if status in ('valide', 'en_attente', 'rejete'):
            professional.status = status

        # Téléphone / Adresse
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

        # Réseaux sociaux
        professional.facebook_url  = (request.form.get('facebook_url')  or '').strip() or None
        professional.instagram_url = (request.form.get('instagram_url') or '').strip() or None
        professional.tiktok_url    = (request.form.get('tiktok_url')    or '').strip() or None
        professional.youtube_url   = (request.form.get('youtube_url')   or '').strip() or None
        professional.social_links_approved = bool(request.form.get('social_links_approved'))

        # ✅ Durée & buffer (optionnels)
        dur_raw = (request.form.get('consultation_duration_minutes') or '').strip()
        if dur_raw != '':
            try:
                professional.consultation_duration_minutes = max(5, min(240, int(dur_raw)))
            except ValueError:
                flash("Durée invalide (minutes).", "error")
        buf_raw = (request.form.get('buffer_between_appointments_minutes') or '').strip()
        if buf_raw != '':
            try:
                professional.buffer_between_appointments_minutes = max(0, min(120, int(buf_raw)))
            except ValueError:
                flash("Délai/buffer invalide (minutes).", "error")

        db.session.commit()
        flash('Professionnel modifié avec succès!')
        return redirect(url_for('admin.admin_professionals'))

    return render_template('edit_product.html', professional=professional)

@admin_bp.route('/professionals/delete/<int:professional_id>', endpoint='delete_professional')
@login_required
def delete_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    professional = Professional.query.get_or_404(professional_id)
    db.session.delete(professional)
    db.session.commit()
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

# --------------------- UTILISATEURS ---------------------
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
        # Conserver l’ancien état pour gérer la promotion et le renommage
        old_username = user.username
        old_type = user.user_type

        username = (request.form.get('username') or user.username).strip()
        email = (request.form.get('email') or user.email).strip().lower()
        user_type = (request.form.get('user_type') or user.user_type).strip()
        is_admin = 'is_admin' in request.form
        new_pw = (request.form.get('new_password') or request.form.get('password') or '').strip()
        phone = (request.form.get('phone') or user.phone or '').strip()

        # Unicité username/email (hors utilisateur courant)
        if User.query.filter(User.username == username, User.id != user.id).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('admin.edit_user', user_id=user.id))
        if User.query.filter(User.email == email, User.id != user.id).first():
            flash("Email déjà enregistré")
            return redirect(url_for('admin.edit_user', user_id=user.id))

        # Appliquer les modifications au User
        user.username = username
        user.email = email
        user.user_type = user_type
        user.is_admin = bool(is_admin)
        user.phone = phone or None
        if new_pw:
            user.password_hash = generate_password_hash(new_pw)

        # ---- PROMOTION AUTO: patient -> professional (sans colonne user_id) ----
        try:
            if user_type == 'professional':
                pro = Professional.query.filter_by(name=username).first()

                if not pro:
                    # Peut-être un pro existe avec l'ancien username => le renommer
                    pro_old = Professional.query.filter_by(name=old_username).first()
                    if pro_old and old_username != username:
                        pro_old.name = username
                        pro = pro_old

                if not pro:
                    # Créer un profil pro minimal
                    pro = Professional(
                        name=username,
                        description="Profil en cours de complétion.",
                        specialty="Psychologue",
                        location="Casablanca",
                        experience_years=0,
                        consultation_fee=0.0,
                        phone=user.phone or None,
                        status="en_attente",
                        # ✅ valeurs par défaut souhaitées si création ici
                        consultation_duration_minutes=45,
                        buffer_between_appointments_minutes=15,
                    )
                    db.session.add(pro)
        except Exception as e:
            flash(f"Attention: la synchronisation du profil professionnel a rencontré un souci: {e}", "warning")

        db.session.commit()
        flash('Utilisateur modifié avec succès!')
        return redirect(url_for('admin.admin_users'))

    return render_template('edit_user.html', user=user)

@admin_bp.route('/users/delete/<int:user_id>', endpoint='delete_user')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin.admin_login'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('Utilisateur supprimé avec succès!')
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

# ✅ Alias de compatibilité : certaines templates utilisent 'admin.admin_orders'
@admin_bp.route('/orders', endpoint='admin_orders')
@login_required
def admin_orders():
    return redirect(url_for('admin.admin_appointments'))

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
        return jsonify({'success': True, 'approved': approved})
    return jsonify({'success': False, 'message': 'Champ social_links_approved non disponible'}), 400
