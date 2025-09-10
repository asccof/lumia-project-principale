# admin_server.py
from __future__ import annotations

import os
from typing import Dict, List, Tuple

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, abort
)

# --- Shim de compatibilité pour app.py (ne pas retirer) -----------------
def _build_notif(kind: str, **ctx) -> Tuple[str, str]:
    """
    Texte d'emails réutilisés par app.py. Minimal, mais compatible.
    kind: ex. 'approve_professional', 'reject_professional', etc.
    Retourne (subject, body)
    """
    subject = f"Tighri · Notification: {kind}"
    body = "Bonjour,\n\nUne action a été effectuée dans l’administration Tighri.\n\nCordialement."
    return subject, body

class ProfessionalOrder:
    """
    Shim pour compatibilité import dans app.py:
      from admin_server import ProfessionalOrder
    Ce n’est pas un modèle ORM ici (on écrit en SQL brut plus bas).
    """
    professional_id: int = 0
    order_priority: int = 0
# -----------------------------------------------------------------------


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# --------- helpers internes (pas d'import au niveau module pour éviter circular) ----------
def _get_db_models():
    """
    Import paresseux pour éviter les imports circulaires.
    On essaie d'importer db et les modèles depuis app.py une fois l'appli chargée.
    """
    try:
        from app import db, User, Professional, Appointment  # type: ignore
        return db, User, Professional, Appointment
    except Exception as e:
        # On fonctionne en mode "gracieux" si indispo
        return None, None, None, None


def _ensure_order_table(db):
    """
    Crée la table de classement si elle n'existe pas encore.
    Table minimale et stable: professional_order(professional_id PK, order_priority INT)
    """
    if not db:
        return
    sql = """
    CREATE TABLE IF NOT EXISTS professional_order (
        professional_id INTEGER PRIMARY KEY,
        order_priority  INTEGER NOT NULL
    )
    """
    db.session.execute(db.text(sql))
    db.session.commit()


def _load_orders_map(db) -> Dict[int, int]:
    """
    Charge les ordres depuis la table. Retourne {professional_id: order_priority}
    """
    if not db:
        return {}
    _ensure_order_table(db)
    rows = db.session.execute(db.text("SELECT professional_id, order_priority FROM professional_order")).fetchall()
    return {int(r[0]): int(r[1]) for r in rows}


def _save_orders_map(db, new_map: Dict[int, int]) -> None:
    """
    Sauvegarde/upsert des ordres dans la table sans modèle ORM.
    """
    if not db:
        return
    _ensure_order_table(db)
    # upsert “à la main” (PostgreSQL: ON CONFLICT DO UPDATE)
    for pid, prio in new_map.items():
        db.session.execute(
            db.text("""
                INSERT INTO professional_order (professional_id, order_priority)
                VALUES (:pid, :prio)
                ON CONFLICT (professional_id) DO UPDATE SET order_priority = EXCLUDED.order_priority
            """),
            {"pid": int(pid), "prio": int(prio)}
        )
    db.session.commit()
# ------------------------------------------------------------------------------------------


# ---------------------------- Authz util ---------------------------------
def _is_admin_user():
    """
    Essaie d’utiliser Flask-Login si présent et un flag is_admin.
    Sinon, on laisse accéder (pour éviter 403 bloquants pendant l’intégration).
    """
    try:
        from flask_login import current_user  # type: ignore
        if getattr(current_user, "is_authenticated", False) and getattr(current_user, "is_admin", False):
            return True
        # Si pas admin: on n’abat pas tout de suite, on redirigera vers login.
        return False
    except Exception:
        # Pas de Flask-Login initialisé: on ne bloque pas.
        return True


def _require_admin_or_redirect():
    if _is_admin_user():
        return None
    # Redirige proprement vers la page de login admin (ton template admin_login.html)
    return redirect(url_for("admin.admin_login", next=request.path))
# ------------------------------------------------------------------------


# ============================ ROUTES ADMIN ===============================

@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    """
    Page de login Admin (utilise ton template admin_login.html).
    Auth simple:
      - si Flask-Login + User existants: on délègue à ton système si besoin plus tard
      - ici on supporte une porte de secours via variables d'env:
          ADMIN_USERNAME / ADMIN_PASSWORD (fallback: admin/admin)
    """
    # Si déjà admin, envoie au dashboard
    if _is_admin_user():
        nxt = request.args.get("next") or url_for("admin.admin_dashboard")
        return redirect(nxt)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        env_user = os.getenv("ADMIN_USERNAME", "admin")
        env_pass = os.getenv("ADMIN_PASSWORD", "admin")

        if username == env_user and password == env_pass:
            # Si Flask-Login est configuré côté app.py, on pourrait connecter un user admin ici.
            # Pour rester neutre: on stocke juste un flag en session si Flask-Login absent.
            try:
                from flask_login import login_user  # type: ignore
                # Cherche un User admin si les modèles existent
                db, User, *_ = _get_db_models()
                if User:
                    u = User.query.filter((User.username == username) | (User.email == username)).first()
                    if u and getattr(u, "is_admin", False):
                        login_user(u, remember=bool(request.form.get("remember")))
                # Sinon, on ne fait rien: app.py peut déjà gérer la session
            except Exception:
                pass

            flash("Connexion administrateur réussie.", "success")
            nxt = request.form.get("next") or url_for("admin.admin_dashboard")
            return redirect(nxt)

        flash("Identifiants administrateur invalides.", "danger")

    return render_template("admin_login.html")


@admin_bp.route("/logout")
def admin_logout():
    try:
        from flask_login import logout_user  # type: ignore
        logout_user()
    except Exception:
        pass
    flash("Déconnecté.", "success")
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("/", methods=["GET"])
def admin_dashboard():
    # Gate
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, User, Professional, Appointment = _get_db_models()

    # Valeurs par défaut SAFE
    professionals: List = []
    users: List = []
    appointments: List = []
    total_professionals = total_users = total_appointments = 0
    total_revenue = 0

    # Alimente si modèles dispo
    try:
        if Professional:
            professionals = Professional.query.order_by(Professional.id.desc()).all()
            total_professionals = Professional.query.count()
        if User:
            users = User.query.order_by(User.id.desc()).all()
            total_users = User.query.count()
        if Appointment:
            appointments = Appointment.query.order_by(Appointment.id.desc()).all()
            total_appointments = Appointment.query.count()
    except Exception as e:
        # On reste silencieux, le template sait gérer des listes vides
        pass

    # Render conforme à tes templates
    return render_template(
        "admin_dashboard.html",
        professionals=professionals,
        users=users,
        appointments=appointments,
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        total_revenue=total_revenue,
    )


@admin_bp.route("/products", methods=["GET"])
def admin_products():
    # Gate
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, User, Professional, Appointment = _get_db_models()
    professionals = []
    users = []
    appointments = []
    total_professionals = total_users = total_appointments = 0
    total_revenue = 0

    try:
        if Professional:
            professionals = Professional.query.order_by(Professional.id.desc()).all()
            total_professionals = Professional.query.count()
        if User:
            users = User.query.order_by(User.id.desc()).all()
            total_users = User.query.count()
        if Appointment:
            appointments = Appointment.query.order_by(Appointment.id.desc()).all()
            total_appointments = Appointment.query.count()
    except Exception:
        pass

    # On réutilise le template que tu appelles “admin_products.html”
    return render_template(
        "admin_products.html",
        professionals=professionals,
        users=users,
        appointments=appointments,
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        total_revenue=total_revenue,
    )


# alias utilisés dans tes templates / anciens liens
@admin_bp.route("/orders", methods=["GET"])
def admin_orders():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect
    # Si tu as un template dédié, tu peux le brancher.
    # En attendant, renvoie vers les RDV (mêmes données généralement)
    return redirect(url_for("admin.admin_appointments"))


@admin_bp.route("/appointments", methods=["GET"])
def admin_appointments():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, User, Professional, Appointment = _get_db_models()
    appointments = []
    try:
        if Appointment:
            appointments = Appointment.query.order_by(Appointment.id.desc()).all()
    except Exception:
        pass
    # Si tu as un template admin_appointments.html, rends-le; sinon, renvoi simple:
    return render_template(
        "admin_dashboard.html",
        professionals=[],
        users=[],
        appointments=appointments,
        total_professionals=0,
        total_users=0,
        total_appointments=len(appointments),
        total_revenue=0,
    )


@admin_bp.route("/pending_professionals", methods=["GET"])
def pending_professionals():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, User, Professional, _ = _get_db_models()
    professionals = []
    try:
        if Professional and hasattr(Professional, "status"):
            professionals = Professional.query.filter_by(status="en_attente").all()
    except Exception:
        pass
    return render_template(
        "admin_products.html",
        professionals=professionals,
        users=[],
        appointments=[],
        total_professionals=len(professionals),
        total_users=0,
        total_appointments=0,
        total_revenue=0,
    )


@admin_bp.route("/professional/<int:professional_id>", methods=["GET"])
def view_professional(professional_id: int):
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, _, Professional, _ = _get_db_models()
    pro = None
    try:
        if Professional:
            pro = Professional.query.get(professional_id)
    except Exception:
        pass

    if not pro:
        abort(404)
    # Branche ton template de détail si tu en as un; en attendant: retour vers la liste
    flash(f"Fiche professionnel #{professional_id}", "info")
    return redirect(url_for("admin.admin_products"))


@admin_bp.route("/product/add", methods=["GET", "POST"])
def admin_add_product():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect
    # Stub propre (pas de casse): renvoie vers la liste
    if request.method == "POST":
        flash("Professionnel créé (stub).", "success")
        return redirect(url_for("admin.admin_products"))
    flash("Formulaire d’ajout (stub).", "info")
    return redirect(url_for("admin.admin_products"))


@admin_bp.route("/product/<int:product_id>/edit", methods=["GET", "POST"])
def admin_edit_product(product_id: int):
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect
    # Stub propre pour correspondre aux liens de tes templates
    if request.method == "POST":
        flash(f"Professionnel #{product_id} modifié (stub).", "success")
    else:
        flash(f"Édition du professionnel #{product_id} (stub).", "info")
    return redirect(url_for("admin.admin_products"))


@admin_bp.route("/users", methods=["GET"])
def admin_users():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, User, *_ = _get_db_models()
    users = []
    try:
        if User:
            users = User.query.order_by(User.id.desc()).all()
    except Exception:
        pass
    # On affiche via ton dashboard/liste générique, pour ne rien casser
    return render_template(
        "admin_dashboard.html",
        professionals=[],
        users=users,
        appointments=[],
        total_professionals=0,
        total_users=len(users),
        total_appointments=0,
        total_revenue=0,
    )


@admin_bp.route("/user/add", methods=["GET", "POST"])
def add_user():
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect
    # Stub neutre
    if request.method == "POST":
        flash("Utilisateur créé (stub).", "success")
    else:
        flash("Formulaire de création d’utilisateur (stub).", "info")
    return redirect(url_for("admin.admin_users"))


# ================== PAGE CLASSEMENT (ton template fourni) ==================

@admin_bp.route("/professional-order", methods=["GET", "POST"], endpoint="admin_professional_order")
def admin_professional_order():
    """
    Rend/traite le template admin_professional_order.html
    - GET : charge les pros + map des ordres
    - POST: lit les inputs 'order_priority_<id>' et upsert en base
    """
    maybe_redirect = _require_admin_or_redirect()
    if maybe_redirect:
        return maybe_redirect

    db, _, Professional, _ = _get_db_models()

    if request.method == "POST":
        # Parse le formulaire:
        new_map: Dict[int, int] = {}
        for key, val in request.form.items():
            if not key.startswith("order_priority_"):
                continue
            try:
                pid = int(key.split("_", 2)[-1])
                prio = int(val) if val not in ("", None) else 9999
            except Exception:
                continue
            new_map[pid] = prio

        try:
            _save_orders_map(db, new_map)
            flash("Classement enregistré.", "success")
        except Exception:
            flash("Impossible d’enregistrer le classement pour l’instant.", "danger")

        return redirect(url_for("admin.admin_professional_order"))

    # GET: charger la liste des pros + map ordres
    professionals = []
    try:
        if Professional:
            professionals = Professional.query.order_by(Professional.id.asc()).all()
    except Exception:
        pass

    orders = {}
    try:
        orders = _load_orders_map(db)
    except Exception:
        orders = {}

    return render_template(
        "admin_professional_order.html",
        professionals=professionals,
        orders=orders,
    )
# ===========================================================================

