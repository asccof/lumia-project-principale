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

# IMPORTANT : on garde les mêmes imports que ton projet utilise déjà
from app import db  # ne pas déplacer: évite de changer l'ordre de boot de ton app
try:
    from app import User, Professional, Appointment  # type: ignore
except Exception:
    from app.models import User, Professional, Appointment  # type: ignore

# ------------------------------------------------------------------------------
# Blueprint
# ------------------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# ------------------------------------------------------------------------------
# Guard: admin_required (compatible avec is_admin ou user_type == "admin")
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
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

# ------------------------------------------------------------------------------
# Dashboard (/admin)
#  - Passe TOUJOURS 'professionals' au template (tes templates l'attendent)
# ------------------------------------------------------------------------------
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    # Pros en attente / valides
    status_col = getattr(Professional, "status", None)
    id_desc = getattr(Professional, "id").desc()

    if status_col is not None:
        pending_pros = _q_all(Professional, status_col == "en_attente", order_by=id_desc)
        valid_pros = _q_all(Professional, status_col == "valide", order_by=id_desc)
    else:
        pending_pros = []
        valid_pros = _q_all(Professional, order_by=id_desc)

    # Tous les pros (pour les sections qui bouclent sur 'professionals')
    professionals = _q_all(Professional, order_by=id_desc)

    # Utilisateurs
    users = _q_all(User, order_by=getattr(User, "id").desc())

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
        professionals=professionals,  # <-- clé attendue par tes templates
    )

# ------------------------------------------------------------------------------
# Liste des professionnels (templates: admin_products.html)
# ------------------------------------------------------------------------------
@admin_bp.route("/professionals", endpoint="admin_products")
@admin_required
def admin_products():
    professionals = _q_all(Professional, order_by=getattr(Professional, "id").desc())
    return render_template("admin_products.html", professionals=professionals)

@admin_bp.route("/professionals/pending", endpoint="pending_professionals")
@admin_required
def pending_professionals():
    status_col = getattr(Professional, "status", None)
    if status_col is None:
        pros = []
    else:
        pros = _q_all(Professional, status_col == "en_attente", order_by=getattr(Professional, "id").desc())
    return render_template("admin_products.html", professionals=pros)

# ------------------------------------------------------------------------------
# Classement / ranking — impl + endpoints (inclut l'alias demandé par les templates)
# ------------------------------------------------------------------------------
def _admin_professional_order_impl():
    """
    Implémentation unique du ranking, réutilisée par les deux endpoints:
    - 'admin_professional_order'  (nom EXACT attendu par admin_base.html)
    - 'admin_professional_order_alias' (si déjà utilisé dans ton app)
    """
    order_col = getattr(Professional, "rating", None)
    if order_col is None:
        order_col = getattr(Professional, "id")
    pros = Professional.query.order_by(order_col.desc()).all()
    return render_template("admin_products.html", professionals=pros)

# Endpoint attendu par tes templates (navigation dans admin_base.html)
@admin_bp.route("/professionals/ranking", endpoint="admin_professional_order")
@admin_required
def admin_professional_order():
    return _admin_professional_order_impl()

# Si ton app utilisait déjà cet alias, on le garde pour compat
@admin_bp.route("/professionals/ranking-alias", endpoint="admin_professional_order_alias")
@admin_required
def admin_professional_order_alias():
    return _admin_professional_order_impl()

# ------------------------------------------------------------------------------
# CRUD Professionnel (avec alias 'product' pour coller aux templates)
# ------------------------------------------------------------------------------
@admin_bp.route("/professionals/add", methods=["GET", "POST"], endpoint="admin_add_product")
@admin_required
def admin_add_product():
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
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel créé.", "success")
        return redirect(url_for("admin.admin_products"))

    professionals = _q_all(Professional, order_by=getattr(Professional, "id").desc())
    return render_template("admin_products.html", professionals=professionals)

# Noms “canon” orientés 'Professional'
@admin_bp.route("/professionals/<int:professional_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        p.status = request.form.get("status", p.status)
        p.consultation_duration_minutes = int(request.form.get("consultation_duration_minutes") or p.consultation_duration_minutes or 45)
        p.buffer_between_appointments_minutes = int(request.form.get("buffer_between_appointments_minutes") or p.buffer_between_appointments_minutes or 15)
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/professionals/<int:professional_id>/delete")
@admin_required
def delete_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    db.session.delete(p)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for("admin.admin_products"))

# --- Alias "product_*" EXACTEMENT comme les templates les appellent ----------------
# NB: tes templates passent 'product_id' dans url_for(..., product_id=p.id)
@admin_bp.route("/professionals/<int:product_id>/edit", methods=["GET", "POST"], endpoint="admin_edit_product")
@admin_required
def _admin_edit_product(product_id: int):
    return edit_professional(product_id)

@admin_bp.route("/professionals/<int:product_id>/delete", endpoint="admin_delete_product")
@admin_required
def _admin_delete_product(product_id: int):
    return delete_professional(product_id)

@admin_bp.route("/professionals/<int:product_id>/view", endpoint="admin_view_product")
@admin_required
def _admin_view_product(product_id: int):
    return view_professional(product_id)

# ------------------------------------------------------------------------------
# Disponibilités (placeholders compatibles)
# ------------------------------------------------------------------------------
@admin_bp.route("/professionals/<int:professional_id>/availability")
@admin_required
def admin_professional_availability(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])

@admin_bp.route("/professionals/<int:professional_id>/unavailable")
@admin_required
def admin_professional_unavailable_slots(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])

# ------------------------------------------------------------------------------
# Commandes / Rendez-vous (compat avec admin_dashboard cards)
# ------------------------------------------------------------------------------
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    orders = []
    try:
        orders = Appointment.query.order_by(
            (getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", Appointment.id)).desc()
        ).limit(50).all()
    except Exception:
        pass
    # On réutilise le dashboard pour afficher des “cards” si besoin
    return render_template(
        "admin_dashboard.html",
        pending_pros=[],
        valid_pros=[],
        users=[],
        last_appts=orders,
        professionals=_q_all(Professional, order_by=getattr(Professional, "id").desc()),
    )

# alias si le template utilise /appointments
@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()

# ------------------------------------------------------------------------------
# Utilisateurs (templates: admin_users.html)
# ------------------------------------------------------------------------------
@admin_bp.route("/users")
@admin_required
def admin_users():
    users = _q_all(User, order_by=getattr(User, "id").desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
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
            is_admin=bool(request.form.get("is_admin")),
        )
        if hasattr(u, "set_password"):
            pwd = request.form.get("password")
            if pwd:
                u.set_password(pwd)
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur créé.", "success")
        return redirect(url_for("admin.admin_users"))

    users = _q_all(User, order_by=getattr(User, "id").desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id: int):
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
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for("admin.admin_users"))

# ------------------------------------------------------------------------------
# Déconnexion
# ------------------------------------------------------------------------------
@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for("login"))

# ------------------------------------------------------------------------------
# Healthcheck
# ------------------------------------------------------------------------------
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
