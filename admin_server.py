# admin_server.py
# Blueprint d'administration Tighri — compatible avec les templates fournis.
from __future__ import annotations

from flask import (
    Blueprint, render_template, render_template_string, request,
    redirect, url_for, flash, jsonify
)
from flask_login import current_user, login_required, logout_user
from sqlalchemy import func, or_
from jinja2 import TemplateNotFound
from datetime import datetime
from functools import wraps

from models import (
    db, User, Professional, Appointment,
    ProfessionalAvailability, UnavailableSlot
)

admin_bp = Blueprint("admin", __name__, template_folder="templates")

# ============ Modèle de classement (utilisé par app.py) ============
class ProfessionalOrder(db.Model):
    __tablename__ = "professional_order"
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(
        db.Integer, db.ForeignKey("professionals.id"),
        unique=True, nullable=False
    )
    order_priority = db.Column(db.Integer, nullable=False, default=999999)

# ============ Guard admin ============
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            flash("Accès admin requis", "danger")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)
    return wrapper

# ============ Notifications réutilisées par app.py ============
def _build_notif(kind: str, ap: Appointment, role: str = "patient"):
    """
    Retourne (subject, body) pour les e-mails.
    kind: 'pending' | 'accepted' | 'refused' | 'reminder'
    role: 'patient' | 'pro'
    """
    p = ap.professional or Professional.query.get(ap.professional_id)
    u = User.query.get(ap.patient_id) if ap.patient_id else None
    pro_name = p.name if p else "Professionnel"
    pat_name = u.username if u else "Patient"
    when = ap.appointment_date.strftime("%d/%m/%Y %H:%M") if ap.appointment_date else "—"
    brand = "Tighri"

    if role == "patient":
        if kind == "pending":
            return (
                f"[{brand}] Demande envoyée",
                f"Bonjour {pat_name},\n\nVotre demande de rendez-vous du {when} "
                f"avec {pro_name} a été envoyée.\nVous recevrez une confirmation bientôt.\n\n{brand}"
            )
        if kind == "accepted":
            return (
                f"[{brand}] Rendez-vous confirmé",
                f"Bonjour {pat_name},\n\nVotre rendez-vous du {when} avec {pro_name} est CONFIRMÉ.\n\n{brand}"
            )
        if kind == "refused":
            return (
                f"[{brand}] Rendez-vous refusé",
                f"Bonjour {pat_name},\n\nVotre demande du {when} avec {pro_name} a été refusée.\n\n{brand}"
            )
        if kind == "reminder":
            return (
                f"[{brand}] Rappel : rendez-vous demain",
                f"Bonjour {pat_name},\n\nRappel : rendez-vous le {when} avec {pro_name}.\n\n{brand}"
            )
    else:  # role == 'pro'
        if kind == "pending":
            return (
                f"[{brand}] Nouvelle demande de rendez-vous",
                f"Bonjour {pro_name},\n\nNouvelle demande pour le {when} de la part de {pat_name}.\n"
                f"Merci de confirmer dans votre espace.\n\n{brand}"
            )

    return (f"[{brand}] Notification", f"{brand}")

# ============ Tableau de bord ============
@admin_bp.get("/", endpoint="admin_dashboard")
@admin_required
def admin_dashboard():
    pending_pros = (
        Professional.query.filter(Professional.status == "en_attente")
        .order_by(Professional.created_at.desc())
        .limit(20).all()
    )
    valid_pros = (
        Professional.query.filter(Professional.status == "valide")
        .order_by(Professional.created_at.desc())
        .limit(20).all()
    )
    users = User.query.order_by(User.id.desc()).limit(20).all()
    last_appts = Appointment.query.order_by(Appointment.id.desc()).limit(20).all()

    # Rendra ton template admin_dashboard.html. Fallback si absent.
    try:
        return render_template(
            "admin_dashboard.html",
            pending_pros=pending_pros,
            valid_pros=valid_pros,
            users=users,
            last_appts=last_appts,
        )
    except TemplateNotFound:
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Admin — Dashboard{% endblock %}
        {% block content %}
        <div class="container py-4">
          <h3>Admin Dashboard (fallback)</h3>
          <p>En attente : {{ pending_pros|length }} — Validés : {{ valid_pros|length }}</p>
          <p>Utilisateurs : {{ users|length }} — Derniers RDV : {{ last_appts|length }}</p>
        </div>
        {% endblock %}
        """, pending_pros=pending_pros, valid_pros=valid_pros, users=users, last_appts=last_appts)

# Déconnexion admin (utilisé dans admin_base.html et admin_users.html)
@admin_bp.get("/logout", endpoint="admin_logout")
@admin_required
def admin_logout():
    logout_user()
    flash("Vous êtes déconnecté(e).", "success")
    return redirect(url_for("login"))

# ============ Utilisateurs ============
@admin_bp.get("/users", endpoint="admin_users")
@admin_required
def admin_users():
    # Recherche optionnelle ?q=...
    q = (request.args.get("q") or "").strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))
    users = query.order_by(User.id.desc()).all()

    try:
        return render_template("admin_users.html", users=users)
    except TemplateNotFound:
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Admin — Utilisateurs{% endblock %}
        {% block content %}
        <div class="container py-4">
          <h3>Utilisateurs (fallback)</h3>
          <ul>
          {% for u in users %}
            <li>#{{u.id}} — {{u.username}} ({{u.email}}) — {{u.user_type}}
              — <a href="{{ url_for('admin.edit_user', user_id=u.id) }}">Éditer</a>
              — <a href="{{ url_for('admin.delete_user', user_id=u.id) }}">Supprimer</a>
            </li>
          {% endfor %}
          </ul>
          <a href="{{ url_for('admin.add_user') }}">Ajouter un utilisateur</a>
        </div>
        {% endblock %}
        """, users=users)

@admin_bp.route("/users/add", methods=["GET", "POST"], endpoint="add_user")
@admin_required
def add_user():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        user_type = (request.form.get("user_type") or "patient").strip()
        is_admin = bool(request.form.get("is_admin"))

        if not username or not email or not password:
            flash("Champs requis manquants.", "warning")
            return redirect(url_for("admin.add_user"))

        if User.query.filter_by(username=username).first() or User.query.filter_by(email=email).first():
            flash("Utilisateur ou email déjà existant.", "danger")
            return redirect(url_for("admin.add_user"))

        from werkzeug.security import generate_password_hash
        u = User(
            username=username, email=email,
            password_hash=generate_password_hash(password),
            user_type=user_type, is_admin=is_admin
        )
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur créé.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Ajouter un utilisateur{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Ajouter un utilisateur</h3>
      <form method="post" class="row g-3">
        <div class="col-md-4"><label class="form-label">Username</label><input name="username" class="form-control" required></div>
        <div class="col-md-4"><label class="form-label">Email</label><input type="email" name="email" class="form-control" required></div>
        <div class="col-md-4"><label class="form-label">Mot de passe</label><input type="password" name="password" class="form-control" required></div>
        <div class="col-md-4">
          <label class="form-label">Type</label>
          <select name="user_type" class="form-select">
            <option value="patient">patient</option>
            <option value="professional">professional</option>
          </select>
        </div>
        <div class="col-md-4 form-check mt-4">
          <input class="form-check-input" type="checkbox" name="is_admin" id="is_admin">
          <label class="form-check-label" for="is_admin">Administrateur</label>
        </div>
        <div class="col-12">
          <button class="btn btn-primary">Créer</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_users') }}">Annuler</a>
        </div>
      </form>
    </div>
    {% endblock %}
    """)

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"], endpoint="edit_user")
@admin_required
def edit_user(user_id):
    u = User.query.get_or_404(user_id)
    if request.method == "POST":
        u.username = (request.form.get("username") or u.username).strip()
        u.email = (request.form.get("email") or u.email).strip().lower()
        u.user_type = (request.form.get("user_type") or u.user_type).strip()
        u.is_admin = bool(request.form.get("is_admin"))
        new_pw = (request.form.get("password") or "").strip()
        if new_pw:
            from werkzeug.security import generate_password_hash
            u.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash("Utilisateur mis à jour.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Éditer utilisateur{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Éditer utilisateur #{{ u.id }}</h3>
      <form method="post" class="row g-3">
        <div class="col-md-4"><label class="form-label">Username</label><input name="username" class="form-control" value="{{ u.username }}"></div>
        <div class="col-md-4"><label class="form-label">Email</label><input type="email" name="email" class="form-control" value="{{ u.email }}"></div>
        <div class="col-md-4"><label class="form-label">Nouveau mot de passe</label><input type="password" name="password" class="form-control" placeholder="(laisser vide)"></div>
        <div class="col-md-4">
          <label class="form-label">Type</label>
          <select name="user_type" class="form-select">
            <option value="patient" {{ 'selected' if u.user_type=='patient' }}>patient</option>
            <option value="professional" {{ 'selected' if u.user_type=='professional' }}>professional</option>
          </select>
        </div>
        <div class="col-md-4 form-check mt-4">
          <input class="form-check-input" type="checkbox" name="is_admin" id="is_admin" {{ 'checked' if u.is_admin }}>
          <label class="form-check-label" for="is_admin">Administrateur</label>
        </div>
        <div class="col-12">
          <button class="btn btn-primary">Enregistrer</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_users') }}">Annuler</a>
        </div>
      </form>
    </div>
    {% endblock %}
    """, u=u)

# ⚠️ Ton template utilise un lien <a href=".../delete"> (GET). On expose donc un GET.
@admin_bp.get("/users/<int:user_id>/delete", endpoint="delete_user")
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.user_type == "professional":
        pro = Professional.query.filter_by(name=user.username).first()
        if pro:
            Appointment.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalAvailability.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            UnavailableSlot.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalOrder.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            db.session.delete(pro)

    if user.user_type == "patient":
        Appointment.query.filter_by(patient_id=user.id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(request.referrer or url_for("admin.admin_users"))

# ============ Professionnels (alias "products" dans tes templates) ============
@admin_bp.get("/professionals", endpoint="admin_products")
@admin_required
def admin_products():
    status = request.args.get("status", "all")
    query = Professional.query
    if status in ("en_attente", "valide", "refuse"):
        query = query.filter(Professional.status == status)
    professionals = query.order_by(Professional.created_at.desc()).all()

    # Ton template fourni : admin_professional.html
    try:
        return render_template("admin_professional.html", professionals=professionals, status=status)
    except TemplateNotFound:
        # Fallback
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Admin — Professionnels{% endblock %}
        {% block content %}
        <div class="container py-4">
          <h3>Professionnels (fallback)</h3>
          <ul>
          {% for p in professionals %}
            <li>#{{p.id}} — {{p.name}} — {{p.status}}
              — <a href="{{ url_for('admin.edit_professional', professional_id=p.id) }}">Éditer</a>
              — <a href="{{ url_for('admin.delete_professional', professional_id=p.id) }}">Supprimer</a>
            </li>
          {% endfor %}
          </ul>
          <a class="btn btn-primary" href="{{ url_for('admin.admin_add_product') }}">Ajouter</a>
        </div>
        {% endblock %}
        """, professionals=professionals, status=status)

# Aliases utilisés par ton dashboard (erreurs précédentes)
@admin_bp.get("/professionals/pending", endpoint="pending_professionals")
@admin_required
def pending_professionals():
    pros = (Professional.query
            .filter(Professional.status == "en_attente")
            .order_by(Professional.created_at.desc())
            .all())
    return render_template("admin_professional.html", professionals=pros, status="en_attente")

@admin_bp.get("/professionals/valid", endpoint="valid_professionals")
@admin_required
def valid_professionals():
    pros = (Professional.query
            .filter(Professional.status == "valide")
            .order_by(Professional.created_at.desc())
            .all())
    return render_template("admin_professional.html", professionals=pros, status="valide")

# Bouton "+ Ajouter" dans admin_professional.html
@admin_bp.route("/professionals/add", methods=["GET", "POST"], endpoint="admin_add_product")
@admin_required
def admin_add_product():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = (request.form.get("password") or "pro12345").strip()
        specialty = (request.form.get("specialty") or "Psychologue").strip()
        location = (request.form.get("location") or "Casablanca").strip()

        if not name or not email:
            flash("Nom et email requis.", "warning")
            return redirect(url_for("admin.admin_add_product"))

        # Crée l'utilisateur pro si absent
        u = User.query.filter_by(email=email).first()
        if not u:
            from werkzeug.security import generate_password_hash
            u = User(
                username=name, email=email,
                password_hash=generate_password_hash(password),
                user_type="professional", is_admin=False
            )
            db.session.add(u); db.session.flush()

        # Crée le profil pro
        p = Professional(
            name=name, description="Profil créé par admin.",
            specialty=specialty, location=location,
            experience_years=0, consultation_fee=0.0,
            availability="disponible", consultation_types="cabinet",
            status="en_attente"
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel ajouté (en_attente).", "success")
        return redirect(url_for("admin.admin_products"))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}+ Ajouter un professionnel{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Ajouter un professionnel</h3>
      <form method="post" class="row g-3">
        <div class="col-md-6"><label class="form-label">Nom complet</label><input name="name" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Email</label><input type="email" name="email" class="form-control" required></div>
        <div class="col-md-6"><label class="form-label">Mot de passe (utilisateur pro)</label><input type="text" name="password" class="form-control" value="pro12345"></div>
        <div class="col-md-6"><label class="form-label">Spécialité</label><input name="specialty" class="form-control" value="Psychologue"></div>
        <div class="col-md-6"><label class="form-label">Ville</label><input name="location" class="form-control" value="Casablanca"></div>
        <div class="col-12">
          <button class="btn btn-primary">Créer</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_products') }}">Annuler</a>
        </div>
      </form>
    </div>
    {% endblock %}
    """)

# Éditer un professionnel (lien dans admin_professional.html)
@admin_bp.route("/professionals/<int:professional_id>/edit", methods=["GET", "POST"], endpoint="edit_professional")
@admin_required
def edit_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        p.name = (request.form.get("name") or p.name).strip()
        p.specialty = (request.form.get("specialty") or p.specialty or "").strip()
        p.location = (request.form.get("location") or p.location or "").strip()
        p.description = (request.form.get("description") or p.description or "").strip()
        p.status = (request.form.get("status") or p.status or "en_attente").strip()
        # Durées optionnelles
        dur = request.form.get("consultation_duration_minutes")
        buf = request.form.get("buffer_between_appointments_minutes")
        try:
            if dur: p.consultation_duration_minutes = max(5, min(240, int(dur)))
            if buf: p.buffer_between_appointments_minutes = max(0, min(120, int(buf)))
        except ValueError:
            flash("Durée/buffer invalides (minutes).", "warning")
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Éditer professionnel{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Éditer professionnel #{{ p.id }}</h3>
      <form method="post" class="row g-3">
        <div class="col-md-6"><label class="form-label">Nom</label><input name="name" class="form-control" value="{{ p.name }}"></div>
        <div class="col-md-6"><label class="form-label">Spécialité</label><input name="specialty" class="form-control" value="{{ p.specialty }}"></div>
        <div class="col-md-6"><label class="form-label">Ville</label><input name="location" class="form-control" value="{{ p.location }}"></div>
        <div class="col-md-6"><label class="form-label">Statut</label>
          <select name="status" class="form-select">
            <option value="en_attente" {{ 'selected' if p.status=='en_attente' }}>en_attente</option>
            <option value="valide" {{ 'selected' if p.status=='valide' }}>valide</option>
            <option value="refuse" {{ 'selected' if p.status=='refuse' }}>refuse</option>
          </select>
        </div>
        <div class="col-md-6"><label class="form-label">Durée (min)</label><input name="consultation_duration_minutes" class="form-control" value="{{ p.consultation_duration_minutes or 45 }}"></div>
        <div class="col-md-6"><label class="form-label">Buffer (min)</label><input name="buffer_between_appointments_minutes" class="form-control" value="{{ p.buffer_between_appointments_minutes or 15 }}"></div>
        <div class="col-12"><label class="form-label">Description</label><textarea name="description" class="form-control" rows="3">{{ p.description }}</textarea></div>
        <div class="col-12">
          <button class="btn btn-primary">Enregistrer</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_products') }}">Annuler</a>
        </div>
      </form>
    </div>
    {% endblock %}
    """, p=p)

# Voir un professionnel (lien "Voir")
@admin_bp.get("/professionals/<int:professional_id>/view", endpoint="view_professional")
@admin_required
def view_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Voir professionnel{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>{{ p.name }}</h3>
      <p><strong>Spécialité:</strong> {{ p.specialty or '-' }}</p>
      <p><strong>Ville:</strong> {{ p.location or '-' }}</p>
      <p><strong>Statut:</strong> {{ p.status }}</p>
      <p><strong>Description:</strong><br>{{ p.description or '—' }}</p>
      <img src="{{ url_for('profile_photo', professional_id=p.id) }}" style="width:160px;height:160px;object-fit:cover;border-radius:10px">
      <div class="mt-3">
        <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_products') }}">Retour</a>
      </div>
    </div>
    {% endblock %}
    """, p=p)

# Disponibilités / Indisponibilités (liens dans ton template)
@admin_bp.route("/professionals/<int:professional_id>/availability", methods=["GET", "POST"], endpoint="admin_professional_availability")
@admin_required
def admin_professional_availability(professional_id):
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        # Écrase toutes les dispos et recrée selon un schéma simple (exemple)
        ProfessionalAvailability.query.filter_by(professional_id=p.id).delete()
        # Exemple : dispo lun-ven 09:00-12:00
        for d in range(5):
            av = ProfessionalAvailability(
                professional_id=p.id, day_of_week=d,
                start_time="09:00", end_time="12:00", is_available=True
            )
            db.session.add(av)
        db.session.commit()
        flash("Disponibilités mises à jour (exemple 09:00-12:00 lun-ven).", "success")
        return redirect(url_for("admin.admin_products"))

    avs = ProfessionalAvailability.query.filter_by(professional_id=p.id).all()
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Disponibilités — {{ p.name }}{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Disponibilités — {{ p.name }}</h3>
      <p class="text-muted">Affichage simple des fenêtres actuelles :</p>
      <ul>
      {% for a in avs %}
        <li>Jour {{ a.day_of_week }} : {{ a.start_time }} - {{ a.end_time }} ({{ 'OK' if a.is_available else 'Non' }})</li>
      {% else %}
        <li>Aucune disponibilité</li>
      {% endfor %}
      </ul>
      <form method="post">
        <button class="btn btn-primary">Remplir un exemple (Lun–Ven 09:00–12:00)</button>
        <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_products') }}">Retour</a>
      </form>
    </div>
    {% endblock %}
    """, p=p, avs=avs)

@admin_bp.route("/professionals/<int:professional_id>/unavailable", methods=["GET", "POST"], endpoint="admin_professional_unavailable_slots")
@admin_required
def admin_professional_unavailable_slots(professional_id):
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        date_str = (request.form.get("date") or "").strip()
        if not date_str:
            flash("Date requise.", "warning")
            return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=p.id))
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Format de date invalide.", "danger")
            return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=p.id))
        start_time = (request.form.get("start_time") or "09:00").strip()
        end_time = (request.form.get("end_time") or "12:00").strip()
        reason = (request.form.get("reason") or "Indisponible").strip()
        slot = UnavailableSlot(
            professional_id=p.id, date=d,
            start_time=start_time, end_time=end_time, reason=reason
        )
        db.session.add(slot); db.session.commit()
        flash("Créneau indisponible ajouté.", "success")
        return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=p.id))

    slots = UnavailableSlot.query.filter_by(professional_id=p.id).order_by(UnavailableSlot.date.desc()).all()
    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Indisponibilités — {{ p.name }}{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Indisponibilités — {{ p.name }}</h3>
      <ul>
      {% for s in slots %}
        <li>{{ s.date }} {{ s.start_time }}–{{ s.end_time }} — {{ s.reason }}</li>
      {% else %}
        <li>Aucune indisponibilité</li>
      {% endfor %}
      </ul>
      <form method="post" class="row g-2">
        <div class="col-md-3"><label class="form-label">Date</label><input type="date" name="date" class="form-control" required></div>
        <div class="col-md-3"><label class="form-label">Début</label><input type="time" name="start_time" class="form-control" value="09:00" required></div>
        <div class="col-md-3"><label class="form-label">Fin</label><input type="time" name="end_time" class="form-control" value="12:00" required></div>
        <div class="col-md-3"><label class="form-label">Raison</label><input name="reason" class="form-control" value="Indisponible"></div>
        <div class="col-12 mt-2"><button class="btn btn-primary">Ajouter</button>
          <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_products') }}">Retour</a></div>
      </form>
    </div>
    {% endblock %}
    """, p=p, slots=slots)

# Valider / Refuser / Supprimer un professionnel (GET pour coller à tes liens)
@admin_bp.get("/professionals/<int:pro_id>/validate", endpoint="admin_validate_professional")
@admin_required
def admin_validate_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = "valide"
    db.session.commit()
    flash(f"Professionnel « {pro.name} » validé.", "success")
    return redirect(request.referrer or url_for("admin.admin_products"))

@admin_bp.get("/professionals/<int:pro_id>/reject", endpoint="admin_reject_professional")
@admin_required
def admin_reject_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = "refuse"
    db.session.commit()
    flash(f"Professionnel « {pro.name} » refusé.", "warning")
    return redirect(request.referrer or url_for("admin.admin_products"))

@admin_bp.get("/professionals/<int:professional_id>/delete", endpoint="delete_professional")
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
    return redirect(request.referrer or url_for("admin.admin_products"))

# ============ Rendez-vous ============
@admin_bp.get("/orders", endpoint="admin_orders")
@admin_required
def admin_orders():
    appts = (Appointment.query
             .order_by(Appointment.appointment_date.desc())
             .limit(200).all())
    try:
        return render_template("admin_orders.html", appointments=appts)
    except TemplateNotFound:
        return render_template_string("""
        {% extends "admin_base.html" %}
        {% block title %}Admin — Rendez-vous{% endblock %}
        {% block content %}
        <div class="container py-4">
          <h3>Rendez-vous (fallback)</h3>
          <ul>
          {% for a in appointments %}
            <li>#{{ a.id }} — {{ a.appointment_date }} — {{ a.status }}</li>
          {% else %}
            <li>Aucun RDV</li>
          {% endfor %}
          </ul>
        </div>
        {% endblock %}
        """, appointments=appts)

@admin_bp.route("/orders/<int:appointment_id>/status", methods=["POST"], endpoint="admin_update_order_status")
@admin_required
def admin_update_order_status(appointment_id):
    new_status = (request.form.get("status") or "").strip()  # 'confirme' | 'annule' | 'en_attente'
    ap = Appointment.query.get_or_404(appointment_id)
    if new_status not in ("confirme", "annule", "en_attente"):
        return jsonify({"ok": False, "error": "status invalide"}), 400
    ap.status = new_status
    db.session.commit()
    flash(f"Rendez-vous #{ap.id} → {new_status}", "success")
    return jsonify({"ok": True})

# ============ Classement ============
@admin_bp.route("/ranking", methods=["GET", "POST"], endpoint="admin_professional_order")
@admin_required
def admin_professional_order():
    if request.method == "POST":
        # Attend un payload { pro_id: priority } x N
        for key, val in request.form.items():
            if not key.startswith("pro_"):  # ex: pro_12
                continue
            try:
                pro_id = int(key.split("_", 1)[1])
                priority = int(val)
            except Exception:
                continue
            po = ProfessionalOrder.query.filter_by(professional_id=pro_id).first()
            if not po:
                po = ProfessionalOrder(professional_id=pro_id, order_priority=priority)
                db.session.add(po)
            else:
                po.order_priority = priority
        db.session.commit()
        flash("Classement mis à jour.", "success")
        return redirect(url_for("admin.admin_professional_order"))

    pros = (Professional.query
            .filter(Professional.status == "valide")
            .order_by(Professional.created_at.desc())
            .all())
    current = { po.professional_id: po.order_priority
                for po in ProfessionalOrder.query.all() }

    return render_template_string("""
    {% extends "admin_base.html" %}
    {% block title %}Classement Professionnels{% endblock %}
    {% block content %}
    <div class="container py-4">
      <h3>Classement (ordre affichage Accueil)</h3>
      <form method="post">
        <div class="table-responsive">
          <table class="table align-middle">
            <thead><tr><th>ID</th><th>Nom</th><th>Priorité (plus petit = plus haut)</th></tr></thead>
            <tbody>
            {% for p in pros %}
              <tr>
                <td>#{{ p.id }}</td>
                <td>{{ p.name }}</td>
                <td style="width:200px">
                  <input class="form-control" type="number" name="pro_{{ p.id }}"
                         value="{{ current.get(p.id, 999999) }}">
                </td>
              </tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        <button class="btn btn-primary">Enregistrer</button>
        <a class="btn btn-outline-secondary" href="{{ url_for('admin.admin_dashboard') }}">Retour</a>
      </form>
    </div>
    {% endblock %}
    """, pros=pros, current=current)
