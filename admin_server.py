# admin_server.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import wraps
from typing import Tuple

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user

# --------------------------------------------------------------------------------------
# NOTE IMPORTS:
# - AUCUN import depuis app.py au niveau module.
# - On charge db et les modèles "à la demande" dans les fonctions (voir _models()).
#   => évite le circular import (app.py -> admin_server -> app.py)
# --------------------------------------------------------------------------------------

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ---------------------------------------------
# Accès lazy à db et aux modèles
# ---------------------------------------------
def _models():
    """Importe db et les modèles quand on en a besoin (évite circular import)."""
    from app import db  # type: ignore
    try:
        # cas courant
        from app import User, Professional, Appointment  # type: ignore
    except Exception:
        # certains projets rangent les modèles ailleurs
        from app.models import User, Professional, Appointment  # type: ignore
    return db, User, Professional, Appointment


# ---------------------------------------------
# Garde admin (compatible is_admin ou user_type='admin')
# ---------------------------------------------
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


# ---------------------------------------------
# Ordres possibles pour les pros (app.py l’a parfois importé)
# ---------------------------------------------
class ProfessionalOrder(str, Enum):
    RATING = "rating"
    RECENT = "recent"


# ---------------------------------------------
# Dashboard
# ---------------------------------------------
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    db, User, Professional, Appointment = _models()

    # Pros valides / en attente (si la colonne existe)
    status_col = getattr(Professional, "status", None)
    id_desc = getattr(Professional, "id").desc()

    if status_col is not None:
        pending_pros = Professional.query.filter(status_col == "en_attente").order_by(id_desc).all()
        valid_pros = Professional.query.filter(status_col == "valide").order_by(id_desc).all()
    else:
        pending_pros = []
        valid_pros = Professional.query.order_by(id_desc).all()

    # Pour compatibilité avec admin_dashboard.html (utilise professionals[:8])
    professionals = valid_pros or pending_pros

    users = User.query.order_by(getattr(User, "id").desc()).all()

    # Derniers rendez-vous si modèle dispo
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
        professionals=professionals,  # <-- clé attendue par ton template
    )


# ---------------------------------------------
# Liste pros (conforme à admin_products.html)
# ---------------------------------------------
@admin_bp.route("/professionals")
@admin_required
def admin_products():
    db, _, Professional, _ = _models()
    pros = Professional.query.order_by(getattr(Professional, "id").desc()).all()
    return render_template("admin_products.html", professionals=pros)


@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals():
    db, _, Professional, _ = _models()
    status_col = getattr(Professional, "status", None)
    if status_col is None:
        pros = []
    else:
        pros = Professional.query.filter(status_col == "en_attente").order_by(getattr(Professional, "id").desc()).all()
    return render_template("admin_products.html", professionals=pros)


@admin_bp.route("/professionals/ranking")
@admin_required
def admin_professional_order():
    db, _, Professional, _ = _models()
    order_col = getattr(Professional, "rating", None) or getattr(Professional, "id")
    pros = Professional.query.order_by(order_col.desc()).all()
    return render_template("admin_products.html", professionals=pros)


@admin_bp.route("/professionals/add", methods=["GET", "POST"])
@admin_required
def admin_add_product():
    db, _, Professional, _ = _models()
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

    pros = Professional.query.order_by(getattr(Professional, "id").desc()).all()
    return render_template("admin_products.html", professionals=pros)


@admin_bp.route("/professionals/<int:professional_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_professional(professional_id: int):
    db, _, Professional, _ = _models()
    p = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        if hasattr(p, "status"):
            p.status = request.form.get("status", getattr(p, "status", None))
        if hasattr(p, "consultation_duration_minutes"):
            p.consultation_duration_minutes = int(
                request.form.get("consultation_duration_minutes") or getattr(p, "consultation_duration_minutes", 45)
            )
        if hasattr(p, "buffer_between_appointments_minutes"):
            p.buffer_between_appointments_minutes = int(
                request.form.get("buffer_between_appointments_minutes")
                or getattr(p, "buffer_between_appointments_minutes", 15)
            )
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))
    return render_template("admin_products.html", professionals=[p])


@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional(professional_id: int):
    db, _, Professional, _ = _models()
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])


@admin_bp.route("/professionals/<int:professional_id>/delete")
@admin_required
def delete_professional(professional_id: int):
    db, _, Professional, _ = _models()
    p = Professional.query.get_or_404(professional_id)
    db.session.delete(p)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for("admin.admin_products"))


# placeholders compatibles si tes templates les appellent
@admin_bp.route("/professionals/<int:professional_id>/availability")
@admin_required
def admin_professional_availability(professional_id: int):
    db, _, Professional, _ = _models()
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])


@admin_bp.route("/professionals/<int:professional_id>/unavailable")
@admin_required
def admin_professional_unavailable_slots(professional_id: int):
    db, _, Professional, _ = _models()
    p = Professional.query.get_or_404(professional_id)
    return render_template("admin_products.html", professionals=[p])


# ---------------------------------------------
# Rendez-vous / commandes (alias appointments)
# ---------------------------------------------
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    db, _, _, Appointment = _models()
    try:
        dt_col = getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
        orders = Appointment.query.order_by((dt_col or Appointment.id).desc()).limit(50).all()
    except Exception:
        orders = []
    # On réutilise le dashboard si tu n’as pas de template dédié
    return render_template(
        "admin_dashboard.html",
        pending_pros=[],
        valid_pros=[],
        users=[],
        last_appts=orders,
        professionals=[],  # pour compat globale
    )


@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    # alias attendu par tes templates (url_for('admin.admin_appointments'))
    return admin_orders()


# ---------------------------------------------
# Utilisateurs (conforme admin_users.html)
# ---------------------------------------------
@admin_bp.route("/users")
@admin_required
def admin_users():
    db, User, _, _ = _models()
    users = User.query.order_by(getattr(User, "id").desc()).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/users/add", methods=["GET", "POST"])
@admin_required
def add_user():
    db, User, _, _ = _models()
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
            is_admin=(request.form.get("is_admin") in ("1", "true", "on")),
        )
        if hasattr(u, "set_password"):
            pwd = request.form.get("password")
            if pwd:
                u.set_password(pwd)
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur créé.", "success")
        return redirect(url_for("admin.admin_users"))

    users = User.query.order_by(getattr(User, "id").desc()).all()
    return render_template("admin_users.html", users=users)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id: int):
    db, User, _, _ = _models()
    u = User.query.get_or_404(user_id)
    if request.method == "POST":
        u.username = request.form.get("username", u.username)
        u.email = request.form.get("email", u.email)
        if hasattr(u, "user_type"):
            u.user_type = request.form.get("user_type", getattr(u, "user_type", None))
        if "is_admin" in request.form and hasattr(u, "is_admin"):
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
    db, User, _, _ = _models()
    u = User.query.get_or_404(user_id)
    db.session.delete(u)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for("admin.admin_users"))


# ---------------------------------------------
# Logout (appelé par tes templates)
# ---------------------------------------------
@admin_bp.route("/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------
# Healthcheck simple
# ---------------------------------------------
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


# ---------------------------------------------
# Notifications: app.py importe _build_notif depuis admin_server.
# On couvre les cas usuels + fallback générique.
# Retourne (subject, body_text)
# ---------------------------------------------
def _build_notif(kind: str, **data) -> Tuple[str, str]:
    """
    Construit un (sujet, corps) en texte brut pour un envoi d'e-mail/notification.

    Args:
        kind: type de notif attendu par app.py (ex: 'pro_pending', 'pro_validated',
              'appt_created', 'appt_cancelled', 'user_registered', etc.)
        **data: champs contextuels (name, email, professional_name, start_time, ...)

    Returns:
        (subject, body) : tuple de strings
    """
    # Helpers
    def _dtfmt(dt) -> str:
        try:
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(dt)

    # Normalisation
    kind = (kind or "").strip().lower()

    # Cas fréquents (on couvre large pour rester compatible avec ton app.py)
    if kind in ("pro_pending", "professional_pending"):
        subject = "Nouveau professionnel en attente de validation"
        body = (
            f"Un professionnel vient de s'inscrire et attend une validation.\n"
            f"Nom: {data.get('professional_name') or data.get('name') or '—'}\n"
            f"Spécialité: {data.get('specialty', '—')}\n"
            f"Email: {data.get('email', '—')}\n"
        )
        return subject, body

    if kind in ("pro_validated", "professional_validated"):
        subject = "Professionnel validé"
        body = (
            f"Le professionnel {data.get('professional_name') or data.get('name') or '—'} a été validé.\n"
        )
        return subject, body

    if kind in ("appt_created", "appointment_created", "order_created"):
        subject = "Nouveau rendez-vous"
        body = (
            f"Rendez-vous créé pour {data.get('user_name', '—')} "
            f"avec {data.get('professional_name', '—')} "
            f"le { _dtfmt(data.get('start_time')) }.\n"
        )
        return subject, body

    if kind in ("appt_cancelled", "appointment_cancelled", "order_cancelled"):
        subject = "Rendez-vous annulé"
        body = (
            f"Le rendez-vous de {data.get('user_name', '—')} "
            f"avec {data.get('professional_name', '—')} "
            f"du { _dtfmt(data.get('start_time')) } a été annulé.\n"
        )
        return subject, body

    if kind in ("user_registered", "signup"):
        subject = "Nouvel utilisateur inscrit"
        body = (
            f"Utilisateur: {data.get('username') or data.get('name') or '—'}\n"
            f"Email: {data.get('email', '—')}\n"
        )
        return subject, body

    if kind in ("password_reset", "pwd_reset"):
        subject = "Réinitialisation du mot de passe"
        body = (
            f"Bonjour {data.get('username') or data.get('name') or '—'},\n"
            f"Une demande de réinitialisation du mot de passe a été reçue.\n"
        )
        return subject, body

    # Fallback générique (sécurise contre tout nouveau kind utilisé par app.py)
    subject = f"Notification: {kind or 'info'}"
    details = "\n".join(f"- {k}: {v}" for k, v in data.items()) or "—"
    body = f"Détails:\n{details}\n"
    return subject, body
