# admin_server.py
from __future__ import annotations

from datetime import datetime
from functools import wraps
from typing import Optional, Dict, Any

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

# -------------------------------------------------------------------
# Blueprint
# -------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# -------------------------------------------------------------------
# Util: notifications (app.py importe ceci)
# -------------------------------------------------------------------
def _build_notif(kind: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """
    Petit helper inoffensif. `app.py` peut l'importer sans créer d'effet de bord.
    Retourne un sujet + contenu texte simples.
    """
    payload = payload or {}
    if kind == "professional_created":
        name = payload.get("name", "Un professionnel")
        return {
            "subject": f"Nouveau professionnel : {name}",
            "body": f"Un nouveau professionnel a été créé : {name}."
        }
    if kind == "appointment_created":
        aid = payload.get("id", "")
        return {
            "subject": f"Rendez-vous #{aid}",
            "body": f"Un rendez-vous a été créé. Détails: {payload!r}"
        }
    # par défaut
    return {
        "subject": f"Notification {kind}",
        "body": f"Détails : {payload!r}"
    }

# -------------------------------------------------------------------
# Classe ORM indépendante (app.py peut l'importer et tenter un JOIN)
# → Ne dépend pas de db.Model pour éviter l'import circulaire
# -------------------------------------------------------------------
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer

class _Base(DeclarativeBase):
    pass

class ProfessionalOrder(_Base):
    __tablename__ = "professional_order"
    # NOTE: structure minimale. Si la table existe : OK. Si non : les requêtes externes échoueront
    # et ton app fait déjà un fallback "featured puis récents".
    professional_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    priority: Mapped[int] = mapped_column(Integer, default=9999)

# -------------------------------------------------------------------
# Decorator admin_required
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# Helpers lecture "safe"
# -------------------------------------------------------------------
def _safe_list(value):
    return value if isinstance(value, list) else (value or [])

def _get_models():
    """
    Import local (à l'appel) pour éviter l'import circulaire au démarrage.
    """
    from app import db, User, Professional, Appointment  # type: ignore
    return db, User, Professional, Appointment

def _q_all(model, *criterion, order_by=None, limit: Optional[int] = None):
    q = model.query
    for c in criterion:
        q = q.filter(c)
    if order_by is not None:
        q = q.order_by(order_by)
    if limit:
        q = q.limit(limit)
    return q.all()

def _q_count(model, *criterion) -> int:
    q = model.query
    for c in criterion:
        q = q.filter(c)
    return q.count()

def _sum_attr(rows, attr: str) -> float:
    total = 0.0
    for r in rows:
        v = getattr(r, attr, 0) or 0
        try:
            total += float(v)
        except Exception:
            pass
    return total

# -------------------------------------------------------------------
# Dashboard  → templates/admin_dashboard.html
# Variables requises : professionals, appointments, users,
# total_professionals, total_users, total_appointments, total_revenue
# -------------------------------------------------------------------
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    db, User, Professional, Appointment = _get_models()

    # Professionals
    try:
        status_col = getattr(Professional, "status", None)
        order_col = getattr(Professional, "id").desc()
        professionals = (
            _q_all(Professional, status_col != "rejete", order_by=order_col)
            if status_col is not None else
            _q_all(Professional, order_by=order_col)
        )
    except Exception:
        professionals = []

    # Users
    try:
        users = _q_all(User, order_by=getattr(User, "id").desc())
    except Exception:
        users = []

    # Appointments
    try:
        dt_col = getattr(Appointment, "appointment_date", None) \
                 or getattr(Appointment, "start_time", None) \
                 or getattr(Appointment, "created_at", None) \
                 or getattr(Appointment, "id")
        appointments = Appointment.query.order_by(dt_col.desc()).limit(50).all()
    except Exception:
        appointments = []

    # Totaux
    try:
        total_professionals = _q_count(Professional)
    except Exception:
        total_professionals = len(_safe_list(professionals))

    try:
        total_users = _q_count(User)
    except Exception:
        total_users = len(_safe_list(users))

    try:
        total_appointments = _q_count(Appointment)
    except Exception:
        total_appointments = len(_safe_list(appointments))

    # Revenu total estimé (fallback si pas de colonne)
    total_revenue = 0.0
    # essais progressifs de champs possibles
    for field in ("price", "amount", "paid_amount", "total_amount"):
        total_revenue = _sum_attr(_safe_list(appointments), field)
        if total_revenue:
            break

    return render_template(
        "admin_dashboard.html",
        professionals=_safe_list(professionals),
        users=_safe_list(users),
        appointments=_safe_list(appointments),
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        total_revenue=total_revenue,
    )

# -------------------------------------------------------------------
# Professionnels → templates/admin_products.html
# Endpoints attendus dans tes templates :
#   - admin.admin_products
#   - admin.pending_professionals
#   - admin.admin_add_product
#   - admin.admin_edit_product(product_id)
#   - admin.view_professional(professional_id)
# -------------------------------------------------------------------
@admin_bp.route("/professionals")
@admin_required
def admin_products():
    db, User, Professional, Appointment = _get_models()

    professionals = _q_all(Professional, order_by=getattr(Professional, "id").desc())
    # mêmes jeux de variables que dashboard (le template les affiche aussi)
    try:
        users = _q_all(User, order_by=getattr(User, "id").desc())
    except Exception:
        users = []
    try:
        dt_col = getattr(Appointment, "appointment_date", None) \
                 or getattr(Appointment, "start_time", None) \
                 or getattr(Appointment, "created_at", None) \
                 or getattr(Appointment, "id")
        appointments = Appointment.query.order_by(dt_col.desc()).limit(50).all()
    except Exception:
        appointments = []

    return render_template(
        "admin_products.html",
        professionals=_safe_list(professionals),
        users=_safe_list(users),
        appointments=_safe_list(appointments),
        total_professionals=len(_safe_list(professionals)),
        total_users=len(_safe_list(users)),
        total_appointments=len(_safe_list(appointments)),
        total_revenue=0,
    )

@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals():
    db, User, Professional, Appointment = _get_models()
    status_col = getattr(Professional, "status", None)
    if status_col is None:
        pros = []
    else:
        pros = _q_all(Professional, status_col == "en_attente", order_by=getattr(Professional, "id").desc())

    # même contexte que products
    try:
        users = _q_all(User, order_by=getattr(User, "id").desc())
    except Exception:
        users = []
    try:
        dt_col = getattr(Appointment, "appointment_date", None) \
                 or getattr(Appointment, "start_time", None) \
                 or getattr(Appointment, "created_at", None) \
                 or getattr(Appointment, "id")
        appointments = Appointment.query.order_by(dt_col.desc()).limit(50).all()
    except Exception:
        appointments = []

    return render_template(
        "admin_products.html",
        professionals=_safe_list(pros),
        users=_safe_list(users),
        appointments=_safe_list(appointments),
        total_professionals=len(_safe_list(pros)),
        total_users=len(_safe_list(users)),
        total_appointments=len(_safe_list(appointments)),
        total_revenue=0,
    )

@admin_bp.route("/professionals/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    db, User, Professional, Appointment = _get_models()
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

    # GET → on réutilise admin_products
    return redirect(url_for("admin.admin_products"))

@admin_bp.route("/professionals/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id: int):
    db, User, Professional, Appointment = _get_models()
    p = Professional.query.get_or_404(product_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        if hasattr(p, "status"):
            p.status = request.form.get("status", getattr(p, "status", None))
        # durées avec fallback
        if hasattr(p, "consultation_duration_minutes"):
            p.consultation_duration_minutes = int(request.form.get("consultation_duration_minutes") or getattr(p, "consultation_duration_minutes", 45) or 45)
        if hasattr(p, "buffer_between_appointments_minutes"):
            p.buffer_between_appointments_minutes = int(request.form.get("buffer_between_appointments_minutes") or getattr(p, "buffer_between_appointments_minutes", 15) or 15)
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))

    # Affichage : on réutilise le template liste en le nourrissant avec [p]
    professionals = [p]
    # Contexte minimal requis par le template
    users = []
    appointments = []
    return render_template(
        "admin_products.html",
        professionals=professionals,
        users=users,
        appointments=appointments,
        total_professionals=len(professionals),
        total_users=len(users),
        total_appointments=len(appointments),
        total_revenue=0,
    )

@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional(professional_id: int):
    db, User, Professional, Appointment = _get_models()
    p = Professional.query.get_or_404(professional_id)
    professionals = [p]
    return render_template(
        "admin_products.html",
        professionals=professionals,
        users=[],
        appointments=[],
        total_professionals=1,
        total_users=0,
        total_appointments=0,
        total_revenue=0,
    )

# -------------------------------------------------------------------
# Classement → templates/admin_professional_order.html
# Endpoints requis : admin.admin_professional_order (GET/POST)
# Contexte : professionals, orders (dict id->priority)
# -------------------------------------------------------------------
@admin_bp.route("/professionals/ranking", methods=["GET", "POST"])
@admin_required
def admin_professional_order():
    db, User, Professional, Appointment = _get_models()

    if request.method == "POST":
        # On stocke l'ordre côté Professional si un champ existe (p.ex. order_priority)
        # Sinon, on peut ignorer silencieusement (et laisser `app.py` gérer via ProfessionalOrder/table dédiée).
        updated = 0
        for p in Professional.query.all():
            key = f"order_priority_{p.id}"
            if key in request.form:
                val = request.form.get(key)
                try:
                    pri = int(val) if val is not None else None
                except Exception:
                    pri = None
                # si le modèle a un champ 'order_priority' ou 'priority' ou 'rank'
                for attr in ("order_priority", "priority", "rank"):
                    if hasattr(p, attr) and pri is not None:
                        setattr(p, attr, pri)
                        updated += 1
                        break
        if updated:
            db.session.commit()
            flash("Classement enregistré.", "success")
        else:
            flash("Aucun champ d’ordre trouvé sur le modèle : valeur ignorée (l’application peut gérer via table ProfessionalOrder).", "warning")
        return redirect(url_for("admin.admin_professional_order"))

    # GET → afficher la grille avec un dict orders
    professionals = _q_all(Professional, order_by=getattr(Professional, "id").asc())
    orders: Dict[int, int] = {}

    # Tenter de lire une priorité depuis le modèle (si champ disponible)
    for p in professionals:
        pri = None
        for attr in ("order_priority", "priority", "rank"):
            if hasattr(p, attr):
                try:
                    pri = int(getattr(p, attr) or 9999)
                except Exception:
                    pri = 9999
                break
        orders[p.id] = pri if pri is not None else 9999

    return render_template(
        "admin_professional_order.html",
        professionals=_safe_list(professionals),
        orders=orders,
    )

# -------------------------------------------------------------------
# RDV / Orders
# Endpoints : admin.admin_orders, admin.admin_appointments (alias)
# -------------------------------------------------------------------
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    db, User, Professional, Appointment = _get_models()
    try:
        dt_col = getattr(Appointment, "appointment_date", None) \
                 or getattr(Appointment, "start_time", None) \
                 or getattr(Appointment, "created_at", None) \
                 or getattr(Appointment, "id")
        appointments = Appointment.query.order_by(dt_col.desc()).limit(100).all()
    except Exception:
        appointments = []

    # Réutilisons le dashboard (il sait afficher la table RDV)
    # et donnons le contexte complet attendu
    try:
        professionals = _q_all(Professional, order_by=getattr(Professional, "id").desc())
    except Exception:
        professionals = []
    try:
        users = _q_all(User, order_by=getattr(User, "id").desc())
    except Exception:
        users = []

    return render_template(
        "admin_dashboard.html",
        professionals=_safe_list(professionals),
        users=_safe_list(users),
        appointments=_safe_list(appointments),
        total_professionals=len(_safe_list(professionals)),
        total_users=len(_safe_list(users)),
        total_appointments=len(_safe_list(appointments)),
        total_revenue=0,
    )

@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()

# -------------------------------------------------------------------
# Utilisateurs → templates/admin_users.html
# Endpoint: admin.admin_users, + add/edit/delete si utiles
# -------------------------------------------------------------------
@admin_bp.route("/users")
@admin_required
def admin_users():
    db, User, Professional, Appointment = _get_models()
    users = _q_all(User, order_by=getattr(User, "id").desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
    db, User, Professional, Appointment = _get_models()
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
        if hasattr(u, "set_password") and request.form.get("password"):
            u.set_password(request.form.get("password"))

        db.session.add(u)
        db.session.commit()
        flash("Utilisateur créé.", "success")
        return redirect(url_for("admin.admin_users"))

    users = _q_all(User, order_by=getattr(User, "id").desc())
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id: int):
    db, User, Professional, Appointment = _get_models()
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
    db, User, Professional, Appointment = _get_models()
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for("admin.admin_users"))

# -------------------------------------------------------------------
# Déconnexion
# -------------------------------------------------------------------
@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for("login"))

# -------------------------------------------------------------------
# Healthcheck
# -------------------------------------------------------------------
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
