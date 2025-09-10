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
from flask_login import (
    current_user,
    login_user,
    logout_user,
)

# IMPORTANT : on évite la boucle d’import ; on ne va toucher qu’à ce fichier.
# On tolère deux organisations possibles : modèles au niveau app.py ou app.models
try:
    from app import db  # type: ignore
    try:
        from app import User, Professional, Appointment  # type: ignore
    except Exception:
        from app.models import User, Professional, Appointment  # type: ignore
except Exception:
    # Dernier recours si l’app range tout dans app.models
    from app.models import db, User, Professional, Appointment  # type: ignore

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ──────────────────────────────────────────────────────────────────────────────
# Décorateur admin : gère l’auth locale et la redirection vers /admin/login
# ──────────────────────────────────────────────────────────────────────────────
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # 1) Non authentifié → on force le login admin (PAS le login pro)
        if not getattr(current_user, "is_authenticated", False):
            return redirect(url_for("admin.admin_login", next=request.url))

        # 2) Authentifié mais pas admin → 403
        is_admin = bool(getattr(current_user, "is_admin", False))
        role = (getattr(current_user, "user_type", "") or "").lower()
        if not (is_admin or role == "admin"):
            abort(403)

        return fn(*args, **kwargs)
    return wrapper


# ──────────────────────────────────────────────────────────────────────────────
# Petits helpers ORM robustes
# ──────────────────────────────────────────────────────────────────────────────
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

def _safe_sum(items, attr_name):
    total = 0.0
    for it in items:
        val = getattr(it, attr_name, None)
        try:
            total += float(val or 0)
        except Exception:
            continue
    return total


# ──────────────────────────────────────────────────────────────────────────────
# Page de connexion ADMIN (utilise ton template admin_login.html)
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username_or_email = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))
        next_url = request.form.get("next") or request.args.get("next") or url_for("admin.admin_dashboard")

        # On autorise login par username OU email
        user = None
        if username_or_email:
            user = User.query.filter(
                (getattr(User, "email").ilike(username_or_email)) |
                (getattr(User, "username").ilike(username_or_email))
            ).first()

        # Vérif mot de passe : on supporte soit user.check_password, soit un champ hash non standard
        ok_pwd = False
        if user:
            if hasattr(user, "check_password"):
                try:
                    ok_pwd = bool(user.check_password(password))
                except Exception:
                    ok_pwd = False
            elif hasattr(user, "password") and isinstance(user.password, str):
                # Si tu utilises werkzeug.security.generate_password_hash
                try:
                    from werkzeug.security import check_password_hash
                    ok_pwd = check_password_hash(user.password, password)
                except Exception:
                    ok_pwd = (user.password == password)  # dernier fallback (dev only)

        if not (user and ok_pwd):
            flash("Identifiants invalides.", "danger")
            return render_template("admin_login.html")

        # Vérifier droit admin
        is_admin = bool(getattr(user, "is_admin", False))
        role = (getattr(user, "user_type", "") or "").lower()
        if not (is_admin or role == "admin"):
            flash("Accès refusé : compte non administrateur.", "danger")
            return render_template("admin_login.html")

        login_user(user, remember=remember)
        return redirect(next_url)

    # GET
    return render_template("admin_login.html")


# ──────────────────────────────────────────────────────────────────────────────
# Tableau de bord
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    # Professionals
    id_desc = getattr(Professional.id, "desc") if hasattr(Professional.id, "desc") else None
    pros = _q_all(Professional, order_by=Professional.id.desc() if id_desc else None, limit=8)

    # Users
    users = _q_all(User, order_by=User.id.desc(), limit=10)

    # Appointments (on essaie plusieurs colonnes usuelles)
    # tri par date si possible, sinon par id desc
    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    appts = []
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = _q_all(Appointment, order_by=Appointment.id.desc(), limit=8)

    # Compteurs
    total_professionals = _q_count(Professional)
    total_users = _q_count(User)
    total_appointments = _q_count(Appointment)

    # Somme de revenue si champ "price" (ou "amount", "total_price")
    total_revenue = 0.0
    if hasattr(Appointment, "price"):
        total_revenue = _safe_sum(Appointment.query.all(), "price")
    elif hasattr(Appointment, "amount"):
        total_revenue = _safe_sum(Appointment.query.all(), "amount")
    elif hasattr(Appointment, "total_price"):
        total_revenue = _safe_sum(Appointment.query.all(), "total_price")

    return render_template(
        "admin_dashboard.html",
        professionals=pros,
        users=users,
        appointments=appts,
        total_professionals=total_professionals,
        total_users=total_users,
        total_appointments=total_appointments,
        total_revenue=total_revenue,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Professionnels (liste / pending / classement / CRUD minimum)
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/professionals")
@admin_required
def admin_products():
    pros = _q_all(Professional, order_by=Professional.id.desc())
    # Réutilisation template admin_products.html (identique au dashboard)
    return render_template(
        "admin_products.html",
        professionals=pros,
        users=_q_all(User, order_by=User.id.desc(), limit=10),
        appointments=_q_all(Appointment, order_by=(getattr(Appointment, "appointment_date", None) or Appointment.id).desc(), limit=8),
        total_professionals=_q_count(Professional),
        total_users=_q_count(User),
        total_appointments=_q_count(Appointment),
        total_revenue=0.0,
    )

@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals():
    status_col = getattr(Professional, "status", None)
    if status_col is None:
        pros = []
    else:
        pros = _q_all(Professional, status_col == "en_attente", order_by=Professional.id.desc())
    return render_template(
        "admin_products.html",
        professionals=pros,
        users=_q_all(User, order_by=User.id.desc(), limit=10),
        appointments=_q_all(Appointment, order_by=(getattr(Appointment, "appointment_date", None) or Appointment.id).desc(), limit=8),
        total_professionals=_q_count(Professional),
        total_users=_q_count(User),
        total_appointments=_q_count(Appointment),
        total_revenue=0.0,
    )

# Classement : endpoint EXACT attendu par tes templates/menu
@admin_bp.route("/professionals/ranking", methods=["GET", "POST"])
@admin_required
def admin_professional_order():
    # On charge les pros
    pros = _q_all(Professional, order_by=Professional.id.desc())

    # On gère le POST pour enregistrer un ordre simple dans un champ 'order_priority' si présent.
    if request.method == "POST":
        updated = 0
        has_order_field = hasattr(Professional, "order_priority")
        for p in pros:
            key = f"order_priority_{p.id}"
            if key in request.form:
                try:
                    val = int(request.form.get(key) or 0)
                    if has_order_field:
                        setattr(p, "order_priority", val)
                        updated += 1
                except Exception:
                    continue
        if updated:
            db.session.commit()
            flash("Classement enregistré.", "success")
        else:
            flash("Aucun champ de classement à mettre à jour dans le modèle Professional.", "warning")

        return redirect(url_for("admin.admin_professional_order"))

    # En GET, on passe un dict { pro.id: order_priority } attendu par ton template
    orders = {}
    if hasattr(Professional, "order_priority"):
        for p in pros:
            orders[p.id] = getattr(p, "order_priority") or 9999

    return render_template("admin_professional_order.html", professionals=pros, orders=orders)

# (Alias si jamais un ancien template utilisait un autre endpoint)
@admin_bp.route("/professionals/ranking/alias", methods=["GET", "POST"])
@admin_required
def admin_professional_order_alias():
    return admin_professional_order()

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
            consultation_duration_minutes=int(request.form.get("consultation_duration_minutes") or 45),
            buffer_between_appointments_minutes=int(request.form.get("buffer_between_appointments_minutes") or 15),
        )
        db.session.add(p)
        db.session.commit()
        flash("Professionnel créé.", "success")
        return redirect(url_for("admin.admin_products"))

    # GET → on renvoie la liste (template unique)
    return admin_products()

@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    return render_template(
        "admin_products.html",
        professionals=[p],
        users=_q_all(User, order_by=User.id.desc(), limit=10),
        appointments=_q_all(Appointment, order_by=(getattr(Appointment, "appointment_date", None) or Appointment.id).desc(), limit=8),
        total_professionals=_q_count(Professional),
        total_users=_q_count(User),
        total_appointments=_q_count(Appointment),
        total_revenue=0.0,
    )

# ⚠️ Endpoint explicitement attendu par tes templates : admin.admin_edit_product
@admin_bp.route("/professionals/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id: int):
    p = Professional.query.get_or_404(product_id)
    if request.method == "POST":
        p.name = request.form.get("name", p.name)
        p.specialty = request.form.get("specialty", p.specialty)
        p.location = request.form.get("location", p.location)
        if hasattr(p, "status"):
            p.status = request.form.get("status", getattr(p, "status", None))
        if hasattr(p, "consultation_duration_minutes"):
            p.consultation_duration_minutes = int(request.form.get("consultation_duration_minutes") or getattr(p, "consultation_duration_minutes", 45))
        if hasattr(p, "buffer_between_appointments_minutes"):
            p.buffer_between_appointments_minutes = int(request.form.get("buffer_between_appointments_minutes") or getattr(p, "buffer_between_appointments_minutes", 15))
        if hasattr(p, "order_priority") and request.form.get("order_priority"):
            try:
                p.order_priority = int(request.form.get("order_priority"))
            except Exception:
                pass
        db.session.commit()
        flash("Professionnel mis à jour.", "success")
        return redirect(url_for("admin.admin_products"))

    return render_template(
        "admin_products.html",
        professionals=[p],
        users=_q_all(User, order_by=User.id.desc(), limit=10),
        appointments=_q_all(Appointment, order_by=(getattr(Appointment, "appointment_date", None) or Appointment.id).desc(), limit=8),
        total_professionals=_q_count(Professional),
        total_users=_q_count(User),
        total_appointments=_q_count(Appointment),
        total_revenue=0.0,
    )

@admin_bp.route("/professionals/<int:professional_id>/delete")
@admin_required
def delete_professional(professional_id: int):
    p = Professional.query.get_or_404(professional_id)
    db.session.delete(p)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for("admin.admin_products"))


# ──────────────────────────────────────────────────────────────────────────────
# RDV / Commandes
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    # On réutilise le dashboard pour lister
    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    orders = []
    try:
        orders = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(50).all()
    except Exception:
        orders = _q_all(Appointment, order_by=Appointment.id.desc(), limit=50)

    return render_template(
        "admin_dashboard.html",
        professionals=_q_all(Professional, order_by=Professional.id.desc(), limit=8),
        users=_q_all(User, order_by=User.id.desc(), limit=10),
        appointments=orders,
        total_professionals=_q_count(Professional),
        total_users=_q_count(User),
        total_appointments=_q_count(Appointment),
        total_revenue=0.0,
    )

@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()


# ──────────────────────────────────────────────────────────────────────────────
# Utilisateurs (liste + add)
# ──────────────────────────────────────────────────────────────────────────────
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

    # GET → affiche liste (pas de template d’édition fourni)
    return admin_users()


# ──────────────────────────────────────────────────────────────────────────────
# Logout (appelé par ton menu)
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/logout")
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    # Après logout, renvoi vers la page de login admin
    return redirect(url_for("admin.admin_login"))


# ──────────────────────────────────────────────────────────────────────────────
# Healthcheck
# ──────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}
