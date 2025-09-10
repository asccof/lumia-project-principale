# admin_server.py
from __future__ import annotations

from datetime import datetime
from functools import wraps
from typing import Tuple

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
# IMPORTANT — imports "légers" pour limiter les risques d'import circulaire
# On suppose que db + modèles sont exposés par app.py (ou app.models)
# -------------------------------------------------------------------
try:
    from app import db  # type: ignore
except Exception:
    # Si ton projet expose db autrement, adapte ici au besoin
    from app import db  # laisser tel quel, Render a déjà booté ainsi

try:
    from app import User, Professional, Appointment  # type: ignore
except Exception:
    from app.models import User, Professional, Appointment  # type: ignore

# -------------------------------------------------------------------
# Modèle "classement" attendu par app.py (au moins ces attributs)
# Même si la table n'existe pas, définir la classe avec ces attributs
# évite les AttributeError, et ton app.py pourra faire son fallback.
# -------------------------------------------------------------------
try:
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy import Integer, Boolean
except Exception:
    # Fallback typing si nécessaire (mais Render installe SQLAlchemy)
    Integer = int  # type: ignore
    Boolean = bool  # type: ignore
    def mapped_column(*args, **kwargs):
        return None
    class Mapped:  # type: ignore
        ...

class ProfessionalOrder(db.Model):  # type: ignore
    __tablename__ = "professional_order"

    # Attributs attendus par ton app.py
    professional_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Optionnel mais pratique si tu fais des "mise en avant" / ordres
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    position: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<ProfessionalOrder professional_id={getattr(self, 'professional_id', None)}>"

# -------------------------------------------------------------------
# Textes d'e-mails / notifications réutilisés par app.py
# -------------------------------------------------------------------
def _build_notif(kind: str, **kwargs) -> Tuple[str, str]:
    """
    Construit (sujet, corps) pour différents e-mails/notifications.
    Ton app.py importe cette fonction, donc elle doit exister ici.
    On garde simple et robuste (pas de dépendance à d'autres modules).
    """
    site = kwargs.get("site_name") or "Tighri"
    if kind == "pro_validated":
        pro_name = kwargs.get("pro_name") or "votre profil"
        subject = f"[{site}] Professionnel validé"
        body = f"Bonjour,\n\n{pro_name} a été validé sur {site}.\n\nCordialement."
        return subject, body
    if kind == "pro_rejected":
        pro_name = kwargs.get("pro_name") or "votre profil"
        subject = f"[{site}] Professionnel refusé"
        body = f"Bonjour,\n\n{pro_name} a été refusé sur {site}.\n\nCordialement."
        return subject, body
    if kind == "new_appointment":
        who = kwargs.get("who") or "Client"
        when = kwargs.get("when") or "bientôt"
        subject = f"[{site}] Nouveau rendez-vous"
        body = f"Bonjour,\n\n{who} a réservé un rendez-vous ({when}).\n\nCordialement."
        return subject, body

    # Par défaut : message générique
    subject = f"[{site}] Notification"
    body = f"Bonjour,\n\nVous avez une notification '{kind}'.\n\nCordialement."
    return subject, body

# -------------------------------------------------------------------
# Blueprint
# -------------------------------------------------------------------
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# -------------------------------------------------------------------
# Garde-fou "admin_required"
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
# Helpers de requêtes
# -------------------------------------------------------------------
def _q_all(model, *criterion, order_by=None):
    q = model.query
    for c in criterion:
        q = q.filter(c)
    if order_by is not None:
        q = q.order_by(order_by)
    return q.all()

def _safe_int(v, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default

# -------------------------------------------------------------------
# Dashboard — DOIT fournir 'professionals' car admin_dashboard.html l'utilise
# -------------------------------------------------------------------
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    # Professionnels "mis en avant" si modèle de classement exploitable
    professionals = []
    try:
        # Si la classe a bien l'attribut professional_id, on peut tenter un tri personnalisé
        if hasattr(ProfessionalOrder, "professional_id"):
            # Tri : featured desc, puis position asc, puis plus récents
            # NB: On fait une jointure souple; si la table n'existe pas réellement,
            # l'app principale gèrera un fallback (et ici on catchera l'exception).
            po = ProfessionalOrder
            professionals = (
                db.session.query(Professional)
                .outerjoin(po, po.professional_id == Professional.id)
                .order_by(
                    (getattr(po, "featured", None) if hasattr(po, "featured") else False).desc()
                    if hasattr(po, "featured") else Professional.id.desc(),
                    (getattr(po, "position", None) if hasattr(po, "position") else 0).asc()
                    if hasattr(po, "position") else Professional.id.desc(),
                    Professional.id.desc(),
                )
                .limit(16)
                .all()
            )
        else:
            # Fallback simple : récents
            professionals = _q_all(Professional, order_by=Professional.id.desc())
    except Exception:
        # Si la table n'existe pas ou autre pb de DB : fallback "récents"
        professionals = _q_all(Professional, order_by=Professional.id.desc())

    # Comptages pour les cartes du dashboard
    try:
        status_col = getattr(Professional, "status", None)
        pending_count = Professional.query.filter(status_col == "en_attente").count() if status_col is not None else 0
        valid_count = Professional.query.filter(status_col == "valide").count() if status_col is not None else Professional.query.count()
    except Exception:
        pending_count = 0
        valid_count = 0

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
        professionals=professionals,   # <— requis par tes templates
        users=users,
        pending_count=pending_count,
        valid_count=valid_count,
        last_appts=last_appts,
    )

# -------------------------------------------------------------------
# Liste des professionnels — correspond à ton template admin_products.html
# -------------------------------------------------------------------
@admin_bp.route("/professionals")
@admin_required
def admin_products():
    professionals = _q_all(Professional, order_by=Professional.id.desc())
    return render_template("admin_products.html", professionals=professionals)

@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals():
    status_col = getattr(Professional, "status", None)
    pros = _q_all(Professional, status_col == "en_attente", order_by=Professional.id.desc()) if status_col is not None else []
    return render_template("admin_products.html", professionals=pros)

@admin_bp.route("/professionals/ranking")
@admin_required
def admin_professional_order():
    # Affiche par "rating" si dispo, sinon par id desc
    order_col = getattr(Professional, "rating", None) or getattr(Professional, "id")
    pros = Professional.query.order_by(order_col.desc()).all()
    return render_template("admin_products.html", professionals=pros)

# Ajout (POST via le même template liste si tu n'as pas de formulaire dédié)
@admin_bp.route("/professionals/add", methods=["GET", "POST"])
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
            consultation_duration_minutes=_safe_int(request.form.get("consultation_duration_minutes"), 45),
            buffer_between_appointments_minutes=_safe_int(request.form.get("buffer_between_appointments_minutes"), 15),
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel créé.", "success")
        return redirect(url_for("admin.admin_products"))

    professionals = _q_all(Professional, order_by=Professional.id.desc())
    return render_template("admin_products.html", professionals=professionals)

# Edition / Vue / Suppression "officiels" (param: professional_id)
@admin_bp.route("/professionals/<int:professional_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        p.status = request.form.get("status", p.status)
        p.consultation_duration_minutes = _safe_int(request.form.get("consultation_duration_minutes"), p.consultation_duration_minutes or 45)
        p.buffer_between_appointments_minutes = _safe_int(request.form.get("buffer_between_appointments_minutes"), p.buffer_between_appointments_minutes or 15)
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

# -------------------------------------------------------------------
# ALIAS demandés par tes templates (utilisent product_id et endpoints précis)
# admin_dashboard.html appelle : url_for('admin.admin_edit_product', product_id=p.id)
# -------------------------------------------------------------------
@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id: int):
    # Redirige vers l’édition "officielle" avec le param attendu
    return edit_professional(product_id)

@admin_bp.route("/products/<int:product_id>/view")
@admin_required
def admin_view_product(product_id: int):
    return view_professional(product_id)

@admin_bp.route("/products/<int:product_id>/delete")
@admin_required
def admin_delete_product(product_id: int):
    return delete_professional(product_id)

# -------------------------------------------------------------------
# Créneaux / indisponibilités (placeholder : on réutilise le template liste)
# -------------------------------------------------------------------
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

# -------------------------------------------------------------------
# Rendez-vous / commandes
# -------------------------------------------------------------------
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    orders = []
    try:
        dt_col = getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
        orders = Appointment.query.order_by((dt_col or Appointment.id).desc()).limit(50).all()
    except Exception:
        pass
    # si tu as un template admin_orders.html, remplace ci-dessous
    return render_template("admin_dashboard.html",
                           professionals=_q_all(Professional, order_by=Professional.id.desc()),
                           users=_q_all(User, order_by=User.id.desc()),
                           pending_count=0,
                           valid_count=0,
                           last_appts=orders)

@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()

# -------------------------------------------------------------------
# Utilisateurs — admin_users.html
# -------------------------------------------------------------------
@admin_bp.route("/users")
@admin_required
def admin_users():
    users = _q_all(User, order_by=User.id.desc())
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

# -------------------------------------------------------------------
# Déconnexion
# -------------------------------------------------------------------
@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    # ton endpoint public de login. Si différent, adapte.
    return redirect(url_for("login"))

# -------------------------------------------------------------------
# Healthcheck
# -------------------------------------------------------------------
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
