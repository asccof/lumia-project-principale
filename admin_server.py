# admin_server.py

from flask import (
    Blueprint, render_template, render_template_string, request,
    redirect, url_for, flash, jsonify
)
from flask_login import current_user, login_required, logout_user
from sqlalchemy import or_, func
from jinja2 import TemplateNotFound
from functools import wraps
from datetime import datetime

from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot

admin_bp = Blueprint('admin', __name__, template_folder='templates')

# =========================
#  Classement des pros (utilisé ailleurs)
# =========================
class ProfessionalOrder(db.Model):
    __tablename__ = 'professional_order'
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), unique=True, nullable=False)
    order_priority = db.Column(db.Integer, nullable=False, default=999999)

# =========================
#  Guard admin
# =========================
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, 'is_admin', False):
            flash("Accès admin requis", "danger")
            return redirect(url_for('index'))
        return fn(*args, **kwargs)
    return wrapper

# =========================
#  Emails (réutilisé par app.py)
# =========================
def _build_notif(kind: str, ap: Appointment, role: str = 'patient'):
    p = ap.professional or Professional.query.get(ap.professional_id)
    u = User.query.get(ap.patient_id) if ap.patient_id else None
    pro_name = p.name if p else "Professionnel"
    pat_name = u.username if u else "Patient"
    when = ap.appointment_date.strftime("%d/%m/%Y %H:%M") if ap.appointment_date else "—"
    brand = "Tighri"

    if role == 'patient':
        if kind == 'pending':
            return (f"[{brand}] Demande envoyée",
                    f"Bonjour {pat_name},\n\nVotre demande de rendez-vous du {when} "
                    f"avec {pro_name} a été envoyée.\nVous recevrez une confirmation bientôt.\n\n{brand}")
        if kind == 'accepted':
            return (f"[{brand}] Rendez-vous confirmé",
                    f"Bonjour {pat_name},\n\nVotre rendez-vous du {when} avec {pro_name} est CONFIRMÉ.\n\n{brand}")
        if kind == 'refused':
            return (f"[{brand}] Rendez-vous refusé",
                    f"Bonjour {pat_name},\n\nVotre demande du {when} avec {pro_name} a été refusée.\n\n{brand}")
        if kind == 'reminder':
            return (f"[{brand}] Rappel : rendez-vous demain",
                    f"Bonjour {pat_name},\n\nRappel : rendez-vous le {when} avec {pro_name}.\n\n{brand}")
    else:
        if kind == 'pending':
            return (f"[{brand}] Nouvelle demande de rendez-vous",
                    f"Bonjour {pro_name},\n\nNouvelle demande pour le {when} de la part de {pat_name}.\n"
                    f"Merci de confirmer dans votre espace.\n\n{brand}")

    return (f"[{brand}] Notification", f"{brand}")

# =========================
#  HOME / DASHBOARD
# =========================
@admin_bp.get('/', endpoint='admin_dashboard')        # utilisé par tes templates
@admin_bp.get('/dashboard', endpoint='admin_home')    # alias si besoin
@admin_required
def admin_dashboard():
    pending_pros = (Professional.query
                    .filter(Professional.status == 'en_attente')
                    .order_by(Professional.created_at.desc())
                    .limit(100).all())
    valid_pros = (Professional.query
                  .filter(Professional.status == 'valide')
                  .order_by(Professional.created_at.desc())
                  .limit(100).all())
    users = User.query.order_by(User.id.desc()).limit(100).all()
    last_appts = Appointment.query.order_by(Appointment.id.desc()).limit(100).all()
    try:
        return render_template('admin_dashboard.html',
                               pending_pros=pending_pros,
                               valid_pros=valid_pros,
                               users=users,
                               last_appts=last_appts)
    except TemplateNotFound:
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Administration Tighri — Tableau de bord{% endblock %}
        {% block content %}
          <div class="row g-3">
            <div class="col-md-3"><div class="card p-3"><div class="h6">En attente</div><div class="display-6">{{ pending_pros|length }}</div></div></div>
            <div class="col-md-3"><div class="card p-3"><div class="h6">Validés</div><div class="display-6">{{ valid_pros|length }}</div></div></div>
            <div class="col-md-3"><div class="card p-3"><div class="h6">Utilisateurs</div><div class="display-6">{{ users|length }}</div></div></div>
            <div class="col-md-3"><div class="card p-3"><div class="h6">Rendez-vous</div><div class="display-6">{{ last_appts|length }}</div></div></div>
          </div>
        {% endblock %}
        """, pending_pros=pending_pros, valid_pros=valid_pros, users=users, last_appts=last_appts)

# =========================
#  DECONNEXION ADMIN (lien dans tes templates)
# =========================
@admin_bp.get('/logout', endpoint='admin_logout')
@admin_required
def admin_logout():
    # on réutilise le logout global de l'app
    try:
        logout_user()
    except Exception:
        pass
    return redirect(url_for('login'))

# =========================
#  UTILISATEURS
# =========================
@admin_bp.get('/users', endpoint='admin_users')
@admin_required
def admin_users():
    q = request.args.get('q', '').strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))
    users = query.order_by(User.id.desc()).all()
    try:
        return render_template('admin_users.html', users=users, q=q)
    except TemplateNotFound:
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Administration Tighri — Utilisateurs{% endblock %}
        {% block content %}
          <h3>Utilisateurs</h3>
          <ul>
          {% for u in users %}
            <li>
              #{{ u.id }} — {{ u.username }} ({{ u.email }}) — {{ u.user_type }}
              <a href="{{ url_for('admin.edit_user', user_id=u.id) }}">Éditer</a> ·
              <a href="{{ url_for('admin.delete_user', user_id=u.id) }}" onclick="return confirm('Supprimer ?')">Supprimer</a>
            </li>
          {% endfor %}
          </ul>
        {% endblock %}
        """, users=users, q=q)

@admin_bp.route('/users/add', methods=['GET', 'POST'], endpoint='add_user')
@admin_required
def add_user():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        pw = (request.form.get('password') or '')
        role = (request.form.get('user_type') or 'patient').strip()
        is_admin = True if request.form.get('is_admin') == '1' else False
        phone = (request.form.get('phone') or '').strip()

        if not username or not email or not pw:
            flash("Nom, email et mot de passe requis.", "warning")
            return redirect(url_for('admin.add_user'))

        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash("Utilisateur déjà existant.", "warning")
            return redirect(url_for('admin.add_user'))

        from werkzeug.security import generate_password_hash
        u = User(username=username, email=email, password_hash=generate_password_hash(pw),
                 user_type=role, is_admin=is_admin, phone=phone or None)
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur ajouté.", "success")
        return redirect(url_for('admin.admin_users'))

    # GET
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Ajouter un utilisateur{% endblock %}
    {% block content %}
      <h3>Ajouter un utilisateur</h3>
      <form method="post" class="card p-3">
        <div class="row g-2">
          <div class="col-md-4"><input class="form-control" name="username" placeholder="Nom d’utilisateur" required></div>
          <div class="col-md-4"><input class="form-control" name="email" placeholder="Email" required></div>
          <div class="col-md-4"><input class="form-control" name="phone" placeholder="Téléphone"></div>
          <div class="col-md-4"><input class="form-control" name="password" type="password" placeholder="Mot de passe" required></div>
          <div class="col-md-4">
            <select class="form-select" name="user_type">
              <option value="patient">Patient</option>
              <option value="professional">Professionnel</option>
            </select>
          </div>
          <div class="col-md-4">
            <select class="form-select" name="is_admin">
              <option value="0">Non admin</option>
              <option value="1">Admin</option>
            </select>
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-primary">Ajouter</button>
          <a class="btn btn-secondary" href="{{ url_for('admin.admin_users') }}">Annuler</a>
        </div>
      </form>
    {% endblock %}
    """)

@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'], endpoint='edit_user')
@admin_required
def edit_user(user_id):
    u = User.query.get_or_404(user_id)
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        role = (request.form.get('user_type') or u.user_type or 'patient').strip()
        is_admin = True if request.form.get('is_admin') == '1' else False
        phone = (request.form.get('phone') or '').strip()
        if username: u.username = username
        if email: u.email = email
        u.user_type = role
        u.is_admin = is_admin
        u.phone = phone or None
        db.session.commit()
        flash("Utilisateur mis à jour.", "success")
        return redirect(url_for('admin.admin_users'))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Éditer utilisateur{% endblock %}
    {% block content %}
      <h3>Éditer utilisateur #{{ u.id }}</h3>
      <form method="post" class="card p-3">
        <div class="row g-2">
          <div class="col-md-4"><input class="form-control" name="username" value="{{ u.username }}" required></div>
          <div class="col-md-4"><input class="form-control" name="email" value="{{ u.email }}" required></div>
          <div class="col-md-4"><input class="form-control" name="phone" value="{{ u.phone or '' }}"></div>
          <div class="col-md-4">
            <select class="form-select" name="user_type">
              <option value="patient" {{ 'selected' if (u.user_type or 'patient')=='patient' else '' }}>Patient</option>
              <option value="professional" {{ 'selected' if (u.user_type or '')=='professional' else '' }}>Professionnel</option>
            </select>
          </div>
          <div class="col-md-4">
            <select class="form-select" name="is_admin">
              <option value="0" {{ 'selected' if not u.is_admin else '' }}>Non admin</option>
              <option value="1" {{ 'selected' if u.is_admin else '' }}>Admin</option>
            </select>
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-primary">Enregistrer</button>
          <a class="btn btn-secondary" href="{{ url_for('admin.admin_users') }}">Annuler</a>
        </div>
      </form>
    {% endblock %}
    """, u=u)

# Ton template utilise <a href="{{ url_for('admin.delete_user', ...) }}"> (GET)
@admin_bp.route('/users/<int:user_id>/delete', methods=['GET', 'POST'], endpoint='delete_user')
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.user_type == 'professional':
        pro = Professional.query.filter_by(name=user.username).first()
        if pro:
            Appointment.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalAvailability.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            UnavailableSlot.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalOrder.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            db.session.delete(pro)

    if user.user_type == 'patient':
        Appointment.query.filter_by(patient_id=user.id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for('admin.admin_users'))

# (on garde aussi une version stricte POST si tu en avais)
@admin_bp.post('/users/<int:user_id>/delete', endpoint='admin_delete_user')
@admin_required
def admin_delete_user(user_id):
    return delete_user(user_id)

# =========================
#  PROFESSIONNELS
# =========================

# Ton sidebar appelle admin.admin_products → on le mappe sur la liste des pros
@admin_bp.get('/products', endpoint='admin_products')
@admin_required
def admin_products():
    pros = Professional.query.order_by(Professional.created_at.desc()).all()
    try:
        return render_template('admin_professionals.html', professionals=pros, status='all')
    except TemplateNotFound:
        # fallback simple
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Professionnels{% endblock %}
        {% block content %}
          <h3>Professionnels</h3>
          <ul>
          {% for p in professionals %}
            <li>
              #{{ p.id }} — {{ p.name }} ({{ p.status }})
              <a href="{{ url_for('admin.edit_professional', professional_id=p.id) }}">Éditer</a> ·
              <a href="{{ url_for('admin.view_professional', professional_id=p.id) }}">Voir</a> ·
              <a href="{{ url_for('admin.delete_professional', professional_id=p.id) }}" onclick="return confirm('Supprimer ?')">Supprimer</a>
            </li>
          {% endfor %}
          </ul>
        {% endblock %}
        """, professionals=pros, status='all')

# Alias si tu utilises /professionals quelque part
@admin_bp.get('/professionals', endpoint='admin_professionals')
@admin_required
def admin_professionals():
    return admin_products()

# + Ajouter (bouton dans ton template pros)
@admin_bp.route('/products/add', methods=['GET', 'POST'], endpoint='admin_add_product')
@admin_required
def admin_add_product():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        specialty = (request.form.get('specialty') or 'Psychologue').strip()
        location = (request.form.get('location') or 'Casablanca').strip()
        description = (request.form.get('description') or 'Profil en cours de complétion.').strip()
        fee = float((request.form.get('consultation_fee') or '0').replace(',', '.') or 0)
        if not name:
            flash("Nom requis.", "warning")
            return redirect(url_for('admin.admin_add_product'))
        pro = Professional(
            name=name, specialty=specialty, location=location,
            description=description, consultation_fee=fee,
            availability='disponible', consultation_types='cabinet',
            status='en_attente'
        )
        db.session.add(pro)
        db.session.commit()
        flash("Professionnel ajouté (en attente).", "success")
        return redirect(url_for('admin.admin_products'))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}+ Ajouter un professionnel{% endblock %}
    {% block content %}
      <h3>Ajouter un professionnel</h3>
      <form method="post" class="card p-3">
        <div class="row g-2">
          <div class="col-md-6"><input class="form-control" name="name" placeholder="Nom" required></div>
          <div class="col-md-3"><input class="form-control" name="specialty" placeholder="Spécialité" value="Psychologue"></div>
          <div class="col-md-3"><input class="form-control" name="location" placeholder="Ville" value="Casablanca"></div>
          <div class="col-md-12"><textarea class="form-control" name="description" placeholder="Description"></textarea></div>
          <div class="col-md-3"><input class="form-control" name="consultation_fee" placeholder="Tarif (MAD)"></div>
        </div>
        <div class="mt-3">
          <button class="btn btn-primary">Ajouter</button>
          <a class="btn btn-secondary" href="{{ url_for('admin.admin_products') }}">Annuler</a>
        </div>
      </form>
    {% endblock %}
    """)

# Éditer (ton template appelle admin.edit_professional)
@admin_bp.route('/professionals/<int:professional_id>/edit', methods=['GET', 'POST'], endpoint='edit_professional')
@admin_required
def edit_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    if request.method == 'POST':
        p.name = (request.form.get('name') or p.name).strip()
        p.specialty = (request.form.get('specialty') or p.specialty or '').strip()
        p.location = (request.form.get('location') or p.location or '').strip()
        p.description = (request.form.get('description') or p.description or '').strip()
        p.consultation_fee = float((request.form.get('consultation_fee') or p.consultation_fee or 0))
        p.status = (request.form.get('status') or p.status or 'en_attente').strip()
        db.session.commit()
        flash("Profil professionnel mis à jour.", "success")
        return redirect(url_for('admin.admin_products'))
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Éditer professionnel{% endblock %}
    {% block content %}
      <h3>Éditer #{{ p.id }} — {{ p.name }}</h3>
      <form method="post" class="card p-3">
        <div class="row g-2">
          <div class="col-md-6"><input class="form-control" name="name" value="{{ p.name }}" required></div>
          <div class="col-md-3"><input class="form-control" name="specialty" value="{{ p.specialty or '' }}"></div>
          <div class="col-md-3"><input class="form-control" name="location" value="{{ p.location or '' }}"></div>
          <div class="col-md-12"><textarea class="form-control" name="description">{{ p.description or '' }}</textarea></div>
          <div class="col-md-3"><input class="form-control" name="consultation_fee" value="{{ p.consultation_fee or 0 }}"></div>
          <div class="col-md-3">
            <select class="form-select" name="status">
              <option value="en_attente" {{ 'selected' if p.status=='en_attente' else '' }}>En attente</option>
              <option value="valide" {{ 'selected' if p.status=='valide' else '' }}>Validé</option>
              <option value="refuse" {{ 'selected' if p.status=='refuse' else '' }}>Refusé</option>
            </select>
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-primary">Enregistrer</button>
          <a class="btn btn-secondary" href="{{ url_for('admin.admin_products') }}">Annuler</a>
        </div>
      </form>
    {% endblock %}
    """, p=p)

# Voir (ton template appelle admin.view_professional)
@admin_bp.get('/professionals/<int:professional_id>', endpoint='view_professional')
@admin_required
def view_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Voir professionnel{% endblock %}
    {% block content %}
      <div class="card p-3">
        <h3>#{{ p.id }} — {{ p.name }}</h3>
        <p><b>Spécialité :</b> {{ p.specialty or '-' }}</p>
        <p><b>Ville :</b> {{ p.location or '-' }}</p>
        <p><b>Tarif :</b> {{ p.consultation_fee or 0 }} MAD</p>
        <p><b>Statut :</b> {{ p.status }}</p>
        <a class="btn btn-secondary" href="{{ url_for('admin.admin_products') }}">← Retour</a>
      </div>
    {% endblock %}
    """, p=p)

# Supprimer pro (ton template utilise un lien GET)
@admin_bp.route('/professionals/<int:professional_id>/delete', methods=['GET', 'POST'], endpoint='delete_professional')
@admin_required
def delete_professional(professional_id):
    pro = Professional.query.get_or_404(professional_id)
    Appointment.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    ProfessionalAvailability.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    UnavailableSlot.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    ProfessionalOrder.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    db.session.delete(pro)
    db.session.commit()
    flash("Profil professionnel supprimé.", "success")
    return redirect(url_for('admin.admin_products'))

# Alias stricte POST si utilisé ailleurs
@admin_bp.post('/professionals/<int:pro_id>/delete', endpoint='admin_delete_professional')
@admin_required
def admin_delete_professional(pro_id):
    return delete_professional(pro_id)

# Valider / Refuser (si tu as des boutons ailleurs)
@admin_bp.post('/professionals/<int:pro_id>/validate', endpoint='admin_validate_professional')
@admin_required
def admin_validate_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = 'valide'
    db.session.commit()
    flash(f"Professionnel « {pro.name} » validé.", "success")
    return redirect(request.referrer or url_for('admin.admin_products'))

@admin_bp.post('/professionals/<int:pro_id>/reject', endpoint='admin_reject_professional')
@admin_required
def admin_reject_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = 'refuse'
    db.session.commit()
    flash(f"Professionnel « {pro.name} » refusé.", "warning")
    return redirect(request.referrer or url_for('admin.admin_products'))

# Disponibilités (liens dans ton template) — mini vue simple
@admin_bp.get('/professionals/<int:professional_id>/availability', endpoint='admin_professional_availability')
@admin_required
def admin_professional_availability(professional_id):
    p = Professional.query.get_or_404(professional_id)
    avs = ProfessionalAvailability.query.filter_by(professional_id=p.id).order_by(
        ProfessionalAvailability.day_of_week.asc(), ProfessionalAvailability.start_time.asc()
    ).all()
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Disponibilités — {{ p.name }}{% endblock %}
    {% block content %}
      <h3>Disponibilités — {{ p.name }}</h3>
      <ul>
        {% for a in avs %}
          <li>Jour {{ a.day_of_week }} : {{ a.start_time }} → {{ a.end_time }}</li>
        {% else %}
          <li>Aucune disponibilité enregistrée.</li>
        {% endfor %}
      </ul>
      <a class="btn btn-secondary" href="{{ url_for('admin.admin_products') }}">← Retour</a>
    {% endblock %}
    """, p=p, avs=avs)

@admin_bp.get('/professionals/<int:professional_id>/unavailable', endpoint='admin_professional_unavailable_slots')
@admin_required
def admin_professional_unavailable_slots(professional_id):
    p = Professional.query.get_or_404(professional_id)
    slots = UnavailableSlot.query.filter_by(professional_id=p.id).order_by(UnavailableSlot.date.desc()).all()
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Indisponibilités — {{ p.name }}{% endblock %}
    {% block content %}
      <h3>Indisponibilités — {{ p.name }}</h3>
      <ul>
        {% for s in slots %}
          <li>{{ s.date }} : {{ s.start_time }} → {{ s.end_time }} — {{ s.reason or '' }}</li>
        {% else %}
          <li>Aucun créneau indisponible.</li>
        {% endfor %}
      </ul>
      <a class="btn btn-secondary" href="{{ url_for('admin.admin_products') }}">← Retour</a>
    {% endblock %}
    """, p=p, slots=slots)

# =========================
#  RDV / ORDERS (lien admin.admin_orders)
# =========================
@admin_bp.get('/orders', endpoint='admin_orders')
@admin_required
def admin_orders():
    appts = Appointment.query.order_by(Appointment.appointment_date.desc()).limit(500).all()
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Rendez-vous{% endblock %}
    {% block content %}
      <h3>Rendez-vous</h3>
      <div class="table-responsive">
        <table class="table table-sm table-striped align-middle">
          <thead><tr><th>ID</th><th>Date</th><th>Pro</th><th>Patient</th><th>Statut</th></tr></thead>
          <tbody>
          {% for a in appts %}
            <tr>
              <td>#{{ a.id }}</td>
              <td>{{ a.appointment_date.strftime("%d/%m/%Y %H:%M") if a.appointment_date else '—' }}</td>
              <td>{{ (a.professional.name if a.professional else a.professional_id) }}</td>
              <td>{{ (a.patient.username if a.patient else a.patient_id) }}</td>
              <td>{{ a.status }}</td>
            </tr>
          {% else %}
            <tr><td colspan="5" class="text-muted">Aucun rendez-vous</td></tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    {% endblock %}
    """, appts=appts)

@admin_bp.post('/orders/<int:appointment_id>/status', endpoint='admin_update_order_status')
@admin_required
def admin_update_order_status(appointment_id):
    new_status = (request.form.get('status') or '').strip()
    ap = Appointment.query.get_or_404(appointment_id)
    if new_status not in ('confirme', 'annule', 'en_attente'):
        return jsonify({'ok': False, 'error': 'status invalide'}), 400
    ap.status = new_status
    db.session.commit()
    flash(f"Rendez-vous #{ap.id} → {new_status}", "success")
    return jsonify({'ok': True})

# =========================
#  CLASSEMENT (lien admin.admin_professional_order)
# =========================
@admin_bp.route('/professional-order', methods=['GET', 'POST'], endpoint='admin_professional_order')
@admin_required
def admin_professional_order():
    if request.method == 'POST':
        # payload: pro_id, order_priority
        try:
            pro_id = int(request.form.get('professional_id') or '0')
            prio = int(request.form.get('order_priority') or '999999')
        except ValueError:
            flash("Valeurs invalides.", "warning")
            return redirect(url_for('admin.admin_professional_order'))
        if not pro_id:
            flash("professional_id requis.", "warning")
            return redirect(url_for('admin.admin_professional_order'))
        po = ProfessionalOrder.query.filter_by(professional_id=pro_id).first()
        if not po:
            po = ProfessionalOrder(professional_id=pro_id, order_priority=prio)
            db.session.add(po)
        else:
            po.order_priority = prio
        db.session.commit()
        flash("Classement mis à jour.", "success")
        return redirect(url_for('admin.admin_professional_order'))

    # GET
    pros = (db.session.query(Professional)
            .outerjoin(ProfessionalOrder, ProfessionalOrder.professional_id == Professional.id)
            .order_by(func.coalesce(ProfessionalOrder.order_priority, 999999).asc(),
                      Professional.created_at.desc(),
                      Professional.id.desc())
            .all())
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Classement des professionnels{% endblock %}
    {% block content %}
      <h3>Classement des professionnels</h3>
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead><tr><th>ID</th><th>Nom</th><th>Statut</th><th>Priorité</th><th>Action</th></tr></thead>
          <tbody>
          {% for p in pros %}
            <tr>
              <td>#{{ p.id }}</td>
              <td>{{ p.name }}</td>
              <td><span class="badge bg-{{ 'success' if p.status=='valide' else ('secondary' if p.status=='en_attente' else 'danger') }}">{{ p.status }}</span></td>
              <td>{{ p.order_priority if p.order_priority is defined else (p.ProfessionalOrder.order_priority if p.ProfessionalOrder else '—') }}</td>
              <td>
                <form method="post" class="d-flex gap-2">
                  <input type="hidden" name="professional_id" value="{{ p.id }}">
                  <input class="form-control form-control-sm" style="width:120px" name="order_priority" placeholder="ex: 10">
                  <button class="btn btn-sm btn-primary">Enregistrer</button>
                </form>
              </td>
            </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    {% endblock %}
    """, pros=pros)
