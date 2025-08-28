# admin_server.py
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
import os
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# --- Flask app ADMIN ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'admin_cle_secrete_ici')
app.config['SESSION_COOKIE_NAME'] = 'tighri_admin_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True  # en prod HTTPS

# --- Normalisation Postgres -> psycopg3 ---
def _normalize_pg_uri(uri: str) -> str:
    if not uri:
        return uri
    if uri.startswith("postgres://"):
        uri = "postgresql://" + uri[len("postgres://"):]
    if uri.startswith("postgresql+psycopg2://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2://"):]
    elif uri.startswith("postgresql+psycopg2cffi://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql+psycopg2cffi://"):]
    elif uri.startswith("postgresql://"):
        uri = "postgresql+psycopg://" + uri[len("postgresql://"):]
    parsed = urlparse(uri)
    q = parse_qs(parsed.query)
    if parsed.scheme.startswith("postgresql+psycopg") and "sslmode" not in q:
        q["sslmode"] = ["require"]
        uri = urlunparse(parsed._replace(query=urlencode({k: v[0] for k, v in q.items()})))
    return uri

db_uri = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_INTERNAL")
if not db_uri:
    raise RuntimeError("DATABASE_URL manquant pour admin_server")
db_uri = _normalize_pg_uri(db_uri)

# --- Réutiliser la même instance SQLAlchemy et les mêmes modèles ---
from models import db, User, Professional, Appointment

app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {"pool_pre_ping": True}
db.init_app(app)  # ne pas recréer une 2e instance

# --- Login ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

@login_manager.user_loader
def load_user(user_id: str):
    try:
        return User.query.get(int(user_id))
    except Exception:
        return None

# ===================== AUTH ADMIN =====================
@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username_or_email = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '')

        # on accepte username ou email
        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email.lower())
        ).first()

        if user and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Identifiants incorrects ou accès non autorisé', 'error')

    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))

# ===================== DASHBOARD =====================
@app.route('/')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    professionals = Professional.query.all()
    users = User.query.all()
    appointments = Appointment.query.all()

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

# ===================== PROFESSIONNELS =====================
@app.route('/products')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    professionals = Professional.query.order_by(Professional.id.desc()).all()
    return render_template('admin_products.html', professionals=professionals)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        # Champs texte
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        specialty = (request.form.get('specialty') or request.form.get('category') or '').strip()
        location = (request.form.get('location') or '').strip()
        image_url = (request.form.get('image_url') or '').strip()
        phone = (request.form.get('phone') or '+212 6 XX XX XX XX').strip()

        # Tarif (price ou consultation_fee)
        fee_raw = (request.form.get('price') or request.form.get('consultation_fee') or '0').replace(',', '.')
        try:
            consultation_fee = float(fee_raw)
        except ValueError:
            consultation_fee = 0.0

        # Expérience
        exp_raw = request.form.get('experience_years') or '0'
        try:
            experience_years = int(exp_raw)
        except ValueError:
            experience_years = 0

        # Disponibilité (availability direct, sinon stock 1/0)
        availability = request.form.get('availability')
        if availability is None:
            stock = (request.form.get('stock') or '').strip().lower()
            availability = 'disponible' if stock in ('1', 'true', 'on', 'yes') else 'indisponible'

        # Types de consultation (liste ou 3 checkboxes)
        types_list = request.form.getlist('consultation_types')
        if not types_list:
            types_list = []
            if request.form.get('home_consultation'): types_list.append('domicile')
            if request.form.get('office_consultation'): types_list.append('cabinet')
            if request.form.get('online_consultation'): types_list.append('en_ligne')
        consultation_types = ','.join(types_list) if types_list else 'cabinet'

        # Validations minimales
        if not name or not description or not specialty:
            flash("Nom, description et spécialité sont obligatoires.", "error")
            return redirect(url_for('admin_add_product'))

        professional = Professional(
            name=name,
            description=description,
            consultation_fee=consultation_fee,
            image_url=image_url,
            specialty=specialty,
            availability=availability,
            consultation_types=consultation_types,
            location=location or 'Casablanca',
            phone=phone,
            experience_years=experience_years,
            status='en_attente'
        )
        db.session.add(professional)
        db.session.commit()
        flash('Professionnel ajouté avec succès!')
        return redirect(url_for('admin_products'))

    return render_template('add_product.html')

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    professional = Professional.query.get_or_404(product_id)

    if request.method == 'POST':
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()

        # alias consultation_fee / price
        fee_raw = (request.form.get('consultation_fee') or request.form.get('price') or '').replace(',', '.')
        if fee_raw:
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                pass

        professional.specialty = (request.form.get('specialty') or request.form.get('category') or professional.specialty).strip()
        professional.image_url = (request.form.get('image_url') or professional.image_url).strip()
        professional.location = (request.form.get('location') or professional.location).strip()
        professional.phone = (request.form.get('phone') or professional.phone).strip()

        # statut si fourni
        status_val = (request.form.get('status') or '').strip()
        if status_val:
            professional.status = status_val

        # availability depuis 'stock' si présent
        stock = request.form.get('stock')
        if stock is not None:
            professional.availability = 'disponible' if stock in ('1', 'true', 'on', 'yes') else 'indisponible'

        # types de consultation si présents
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

        # experience si fourni
        exp_raw = request.form.get('experience_years')
        if exp_raw:
            try:
                professional.experience_years = int(exp_raw)
            except ValueError:
                pass

        db.session.commit()
        flash('Professionnel modifié avec succès!')
        return redirect(url_for('admin_products'))

    return render_template('edit_product.html', professional=professional)

@app.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    professional = Professional.query.get_or_404(product_id)
    db.session.delete(professional)
    db.session.commit()
    return jsonify({'success': True, 'message': 'Professionnel supprimé avec succès'})

# Variante liste/CRUD par /professionals (templates qui l’utilisent)
@app.route('/professionals')
@login_required
def admin_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    professionals = Professional.query.all()
    return render_template('admin_professionals.html', professionals=professionals)

@app.route('/professionals/add', methods=['GET', 'POST'])
@login_required
def add_professional():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        description = (request.form.get('description') or '').strip()
        fee_raw = (request.form.get('consultation_fee') or '0').replace(',', '.')
        try:
            consultation_fee = float(fee_raw)
        except ValueError:
            consultation_fee = 0.0
        specialty = (request.form.get('specialty') or '').strip()
        location = (request.form.get('location') or '').strip()
        exp_raw = request.form.get('experience_years') or '0'
        try:
            experience_years = int(exp_raw)
        except ValueError:
            experience_years = 0
        image_url = (request.form.get('image_url') or '').strip()

        if not name or not description or not specialty:
            flash("Nom, description et spécialité sont obligatoires.", "error")
            return redirect(url_for('add_professional'))

        professional = Professional(
            name=name,
            description=description,
            consultation_fee=consultation_fee,
            specialty=specialty,
            location=location or 'Casablanca',
            experience_years=experience_years,
            image_url=image_url,
            status='en_attente'
        )
        db.session.add(professional)
        db.session.commit()
        flash('Professionnel ajouté avec succès!')
        return redirect(url_for('admin_professionals'))

    return render_template('add_professional.html')

@app.route('/professionals/edit/<int:professional_id>', methods=['GET', 'POST'])
@login_required
def edit_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    professional = Professional.query.get_or_404(professional_id)

    if request.method == 'POST':
        professional.name = (request.form.get('name') or professional.name).strip()
        professional.description = (request.form.get('description') or professional.description).strip()
        fee_raw = (request.form.get('consultation_fee') or '').replace(',', '.')
        if fee_raw:
            try:
                professional.consultation_fee = float(fee_raw)
            except ValueError:
                pass
        professional.specialty = (request.form.get('specialty') or professional.specialty).strip()
        professional.location = (request.form.get('location') or professional.location).strip()
        exp_raw = request.form.get('experience_years')
        if exp_raw:
            try:
                professional.experience_years = int(exp_raw)
            except ValueError:
                pass
        professional.image_url = (request.form.get('image_url') or professional.image_url).strip()
        db.session.commit()
        flash('Professionnel modifié avec succès!')
        return redirect(url_for('admin_professionals'))

    return render_template('edit_professional.html', professional=professional)

@app.route('/professionals/delete/<int:professional_id>')
@login_required
def delete_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    professional = Professional.query.get_or_404(professional_id)
    db.session.delete(professional)
    db.session.commit()
    flash('Professionnel supprimé avec succès!')
    return redirect(url_for('admin_professionals'))

@app.route('/professionals/<int:professional_id>')
@login_required
def view_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    professional = Professional.query.get_or_404(professional_id)
    appointments = Appointment.query.filter_by(professional_id=professional_id).all()
    return render_template('view_professional.html', professional=professional, appointments=appointments)

# ===================== UTILISATEURS =====================
@app.route('/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    users = User.query.order_by(User.id.desc()).all()
    return render_template('admin_users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        password = (request.form.get('password') or '')
        user_type = (request.form.get('user_type') or 'patient').strip()
        is_admin = 'is_admin' in request.form

        if not username or not email or not password:
            flash("Tous les champs sont obligatoires")
            return redirect(url_for('add_user'))

        if User.query.filter_by(username=username).first():
            flash("Nom d'utilisateur déjà utilisé")
            return redirect(url_for('add_user'))
        if User.query.filter_by(email=email).first():
            flash("Email déjà utilisé")
            return redirect(url_for('add_user'))

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            user_type=user_type,
            is_admin=bool(is_admin)
        )
        db.session.add(user)
        db.session.commit()
        flash('Utilisateur ajouté avec succès!')
        return redirect(url_for('admin_users'))

    return render_template('add_user.html')

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        username = (request.form.get('username') or user.username).strip()
        email = (request.form.get('email') or user.email).strip().lower()
        user_type = (request.form.get('user_type') or user.user_type).strip()
        is_admin = 'is_admin' in request.form
        new_pw = (request.form.get('new_password') or request.form.get('password') or '').strip()

        # Unicité
        if User.query.filter(User.username == username, User.id != user.id).first():
            flash("Nom d'utilisateur déjà pris")
            return redirect(url_for('edit_user', user_id=user.id))
        if User.query.filter(User.email == email, User.id != user.id).first():
            flash("Email déjà enregistré")
            return redirect(url_for('edit_user', user_id=user.id))

        user.username = username
        user.email = email
        user.user_type = user_type
        user.is_admin = bool(is_admin)

        if new_pw:
            user.password_hash = generate_password_hash(new_pw)

        db.session.commit()
        flash('Utilisateur modifié avec succès!')
        return redirect(url_for('admin_users'))

    return render_template('edit_user.html', user=user)

@app.route('/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('Utilisateur supprimé avec succès!')
    return redirect(url_for('admin_users'))

# ===================== RDV / COMMANDES =====================
@app.route('/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    appointments = Appointment.query.order_by(Appointment.appointment_date.desc()).all()
    return render_template('admin_orders.html', appointments=appointments)

@app.route('/appointments')
@login_required
def admin_appointments():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    appointments = Appointment.query.order_by(Appointment.appointment_date.desc()).all()
    return render_template('admin_appointments.html', appointments=appointments)

@app.route('/orders/<int:appointment_id>/status', methods=['POST'])
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

# ===================== API STATS & VALIDATION =====================
@app.route('/api/stats')
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

@app.route('/professionals/<int:professional_id>/validate', methods=['POST'])
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

@app.route('/professionals/<int:professional_id>/reject', methods=['POST'])
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

@app.route('/pending-professionals')
@login_required
def pending_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    pending_professionals = Professional.query.filter_by(status='en_attente').all()
    return render_template('pending_professionals.html', professionals=pending_professionals)

# ===================== MAIN (local seulement) =====================
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@tighri.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional'
            )
            db.session.add(admin)
            db.session.commit()
    app.run(debug=True, port=8080)
