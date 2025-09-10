# admin_server.py
from __future__ import annotations

from datetime import datetime
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, logout_user

# -----------------------------------------------------------------------------
# Export attendu par app.py
# -----------------------------------------------------------------------------
def _build_notif(kind: str, **ctx) -> str:
    """
    Construit un petit message texte/HTML pour les notifications e-mail/flash.
    Ne dépend pas de la DB. `app.py` importe cette fonction.
    """
    # Tu peux affiner les textes si besoin. On reste volontairement simple.
    if kind == "pro_validated":
        return f"Le professionnel « {ctx.get('name','')} » a été validé."
    if kind == "pro_created":
        return f"Nouveau professionnel « {ctx.get('name','')} » créé."
    if kind == "user_created":
        return f"Nouvel utilisateur « {ctx.get('username','')} » créé."
    if kind == "appointment_created":
        return f"Rendez-vous créé pour le {ctx.get('when','')}."
    return ctx.get("message") or "Notification"

class ProfessionalOrder:
    """
    Classe minimale exportée parce que ton app.py peut l'importer.
    On évite toute dépendance SQLAlchemy ici pour ne pas recréer de cycle.
    L'app loggue un warning et fait un fallback si cette classe n'a pas de colonnes.
    """
    # Ajouter des attributs statiques pour éviter AttributeError en accès direct
    professional_id = None
    priority = None
    score = None

# -----------------------------------------------------------------------------
# Blueprint
# -----------------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# -----------------------------------------------------------------------------
# Garde-fou "admin_required"
# -----------------------------------------------------------------------------
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        is_admin = bool(getattr(current_user, "is_admin", False))
        role = (getattr(current_user, "user_type", None) or "").lower()
        if not (is_admin or role == "admin"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper

# -----------------------------------------------------------------------------
# Imports paresseux de la DB et des modèles (pour casser la boucle d'import)
# -----------------------------------------------------------------------------
def _get_db_and_models():
    """
    Import local (tardif) pour éviter le cycle:
    app.py peut importer _build_notif/admin_bp sans que ici on touche à db.
    """
    try:
        from app import db, User, Professional, Appointment  # type: ignore
        return db, User, Professional, Appointment
    except Exception:
        # Certains projets rangent les modèles dans app.models
        from app import db  # type: ignore
        from app.models import User, Professional, Appointment  # type: ignore
        return db, User, Professional, Appointment

# -----------------------------------------------------------------------------
# Helpers lecture "safe"
# -----------------------------------------------------------------------------
def _q_all(model, *criterion, order_by=None, limit=None):
    q = model.query
    for c in criterion:
        q = q.filter(c)
    if order_by is not None:
        q = q.order_by(order_by)
    if limit:
        q = q.limit(limit)
    return q.all()

def _q_count(model, *criterion):
    q = model.query
    for c in criterion:
        q = q.filter(c)
    return q.count()

# -----------------------------------------------------------------------------
# Dashboard
# -----------------------------------------------------------------------------
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    db, User, Professional, Appointment = _get_db_and_models()

    # Colonnes « robustes »
    pro_id_desc = getattr(Professional.id, "desc", lambda: None)
    order_desc = pro_id_desc() if callable(pro_id_desc) else None

    status_col = getattr(Professional, "status", None)
    featured_col = getattr(Professional, "featured", None)

    # Listes pros pour les sections "en attente" / "validés" + bloc "professionals"
    if status_col is not None:
        pending_pros = _q_all(Professional, status_col == "en_attente", order_by=Professional.id.desc())
        valid_pros = _q_all(Professional, status_col == "valide", order_by=Professional.id.desc())
    else:
        pending_pros = []
        valid_pros = _q_all(Professional, order_by=Professional.id.desc())

    # Section "professionals" utilisée par ton admin_dashboard.html
    try:
        if featured_col is not None:
            professionals = (
                Professional.query.order_by(
                    getattr(Professional, "featured", 0).desc(),
                    Professional.id.desc(),
                ).limit(12).all()
            )
        else:
            professionals = _q_all(Professional, order_by=Professional.id.desc(), limit=12)
    except Exception:
        professionals = []

    users = _q_all(User, order_by=User.id.desc())

    # Derniers rendez-vous
    last_appts = []
    try:
        dt_col = getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
        last_appts = Appointment.query.order_by((dt_col or Appointment.id).desc()).limit(10).all()
    except Exception:
        pass

    return render_template(
        "admin_dashboard.html",
        pending_pros=pending_pros,
        valid_pros=valid_pros,
        users=users,
        last_appts=last_appts,
        professionals=professionals,  # IMPORTANT: clé attendue par le template
    )

# -----------------------------------------------------------------------------
# Produits = Professionnels (compat: tes templates utilisent "products")
# -----------------------------------------------------------------------------
@admin_bp.route("/products")
@admin_required
def admin_products():
    db, User, Professional, Appointment = _get_db_and_models()
    professionals = _q_all(Professional, order_by=Professional.id.desc())
    return render_template("admin_products.html", professionals=professionals)

# Alias “professionals” pour compat ascendante
@admin_bp.route("/professionals")
@admin_required
def admin_products_alias():
    return admin_products()

@admin_bp.route("/products/pending")
@admin_required
def pending_products():
    db, User, Professional, Appointment = _get_db_and_models()
    status_col = getattr(Professional, "status", None)
    if status_col is None:
        pros = []
    else:
        pros = _q_all(Professional, status_col == "en_attente", order_by=Professional.id.desc())
    return render_template("admin_products.html", professionals=pros)

@admin_bp.route("/products/ranking")
@admin_required
def admin_product_order():
    db, User, Professional, Appointment = _get_db_and_models()
    order_col = getattr(Professional, "rating", None) or getattr(Professional, "score", None)
    if order_col is None:
        order_col = Professional.id
    pros = Professional.query.order_by(order_col.desc()).all()
    return render_template("admin_products.html", professionals=pros)

@admin_bp.route("/products/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    db, User, Professional, Appointment = _get_db_and_models()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Le nom est obligatoire.", "warning")
            return redirect(url_for("admin.admin_add_product"))

        p = Professional(
            name=name,
            specialty=request.form.get("specialty"),
            location=request.form.get("location"),
            status=request.form.get("status") or "en_attente",
            consultation_duration_minutes=int(request.form.get("consultation_duration_minutes") or 45),
            buffer_between_appointments_minutes=int(request.form.get("buffer_between_appointments_minutes") or 15),
            featured=bool(request.form.get("featured")) if hasattr(Professional, "featured") else None,
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel créé.", "success")
        return redirect(url_for("admin.admin_products"))

    professionals = _q_all(Professional, order_by=Professional.id.desc())
    return render_template("admin_products.html", professionals=professionals)

@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    p = Professional.query.get_or_404(product_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        if hasattr(p, "status"):
            p.status = request.form.get("status", getattr(p, "status", None))
        if hasattr(p, "featured"):
            p.featured = request.form.get("featured") in ("1", "true", "on")
        p.consultation_duration_minutes = int(request.form.get("consultation_duration_minutes") or getattr(p, "consultation_duration_minutes", 45) or 45)
        p.buffer_between_appointments_minutes = int(request.form.get("buffer_between_appointments_minutes") or getattr(p, "buffer_between_appointments_minutes", 15) or 15)
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/products/<int:product_id>/view")
@admin_required
def admin_view_product(product_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    p = Professional.query.get_or_404(product_id)
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/products/<int:product_id>/delete")
@admin_required
def admin_delete_product(product_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    p = Professional.query.get_or_404(product_id)
    db.session.delete(p)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for("admin.admin_products"))

@admin_bp.route("/products/<int:product_id>/availability")
@admin_required
def admin_product_availability(product_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    p = Professional.query.get_or_404(product_id)
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/products/<int:product_id>/unavailable")
@admin_required
def admin_product_unavailable_slots(product_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    p = Professional.query.get_or_404(product_id)
    return render_template("admin_products.html", professionals=[p])

# --- Alias exacts "professionals/*" pour compat (si tes templates les utilisent) ---
@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals_alias():
    return pending_products()

@admin_bp.route("/professionals/ranking")
@admin_required
def admin_professional_order_alias():
    return admin_product_order()

@admin_bp.route("/professionals/add", methods=["GET", "POST"])
@admin_required
def admin_add_professional_alias():
    return admin_add_product()

@admin_bp.route("/professionals/<int:professional_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_professional_alias(professional_id: int):
    return admin_edit_product(professional_id)

@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional_alias(professional_id: int):
    return admin_view_product(professional_id)

@admin_bp.route("/professionals/<int:professional_id>/delete")
@admin_required
def delete_professional_alias(professional_id: int):
    return admin_delete_product(professional_id)

@admin_bp.route("/professionals/<int:professional_id>/availability")
@admin_required
def admin_professional_availability_alias(professional_id: int):
    return admin_product_availability(professional_id)

@admin_bp.route("/professionals/<int:professional_id>/unavailable")
@admin_required
def admin_professional_unavailable_slots_alias(professional_id: int):
    return admin_product_unavailable_slots(professional_id)

# -----------------------------------------------------------------------------
# Commandes / Rendez-vous
# -----------------------------------------------------------------------------
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    db, User, Professional, Appointment = _get_db_and_models()
    try:
        dt_col = getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None) or Appointment.id
        orders = Appointment.query.order_by(dt_col.desc()).limit(50).all()
    except Exception:
        orders = []
    # On réutilise le dashboard pour afficher la liste (si tu as admin_orders.html, remplace ici)
    return render_template(
        "admin_dashboard.html",
        pending_pros=[],
        valid_pros=[],
        users=[],
        last_appts=orders,
        professionals=_q_all(Professional, order_by=Professional.id.desc(), limit=12),
    )

@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()

# -----------------------------------------------------------------------------
# Utilisateurs
# -----------------------------------------------------------------------------
@admin_bp.route("/users")
@admin_required
def admin_users():
    db, User, Professional, Appointment = _get_db_and_models()
    users = _q_all(User, order_by=User.id.desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
    db, User, Professional, Appointment = _get_db_and_models()
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        if not username or not email:
            flash("Nom d’utilisateur et e-mail sont obligatoires.", "warning")
            return redirect(url_for("admin.add_user"))

        u = User(
            username=username,
            email=email,
            user_type=request.form.get("user_type") or "patient",
            is_admin=request.form.get("is_admin") in ("1", "true", "on"),
        )
        if hasattr(u, "set_password"):
            pwd = request.form.get("password")
            if pwd:
                u.set_password(pwd)
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur créé.", "success")
        return redirect(url_for("admin.admin_users"))

    users = _q_all(User, order_by=User.id.desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    u = User.query.get_or_404(user_id)
    if request.method == "POST":
        u.username = request.form.get("username", u.username)
        u.email = request.form.get("email", u.email)
        u.user_type = request.form.get("user_type", u.user_type)
        if "is_admin" in request.form:
            u.is_admin = request.form.get("is_admin") in ("1", "true", "on")
        if hasattr(u, "set_password") and request.form.get("password"):
            u.set_password(request.form.get("password"))
        db.session.commit()
        flash("Utilisateur mis à jour.", "success")
        return redirect(url_for("admin.admin_users"))
    return render_template("admin_users.html", users=[u])

@admin_bp.route("/users/<int:user_id>/delete")
@admin_required
def delete_user(user_id: int):
    db, User, Professional, Appointment = _get_db_and_models()
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for("admin.admin_users"))

# -----------------------------------------------------------------------------
# Déconnexion
# -----------------------------------------------------------------------------
@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for("login"))

# -----------------------------------------------------------------------------
# Healthcheck
# -----------------------------------------------------------------------------
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
