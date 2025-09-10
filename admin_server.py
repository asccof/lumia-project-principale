# admin_server.py
from __future__ import annotations
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, url_for
)
from flask_login import current_user, login_user, logout_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─────────────────────────────────────────────────────────────
# Utilitaires : imports tardifs pour éviter tout import circulaire
# ─────────────────────────────────────────────────────────────
def _models():
    """
    Importe tardivement db et les modèles depuis app.py
    (app.py est alors entièrement chargé → pas de boucle).
    """
    from app import db, User, Professional, Appointment  # type: ignore
    return db, User, Professional, Appointment


# ─────────────────────────────────────────────────────────────
# Accès admin
# ─────────────────────────────────────────────────────────────
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_authenticated", False):
            return redirect(url_for("admin.admin_login", next=request.url))
        is_admin = bool(getattr(current_user, "is_admin", False))
        role = (getattr(current_user, "user_type", "") or "").lower()
        if not (is_admin or role == "admin"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


# ─────────────────────────────────────────────────────────────
# Login admin (utilise ton template admin_login.html)
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        db, User, _, _ = _models()
        username_or_email = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))
        next_url = request.form.get("next") or request.args.get("next") or url_for("admin.admin_dashboard")

        user = None
        if username_or_email:
            try:
                user = User.query.filter(
                    (User.email.ilike(username_or_email)) | (User.username.ilike(username_or_email))
                ).first()
            except Exception:
                user = None

        ok_pwd = False
        if user:
            if hasattr(user, "check_password"):
                try:
                    ok_pwd = bool(user.check_password(password))
                except Exception:
                    ok_pwd = False
            elif hasattr(user, "password") and isinstance(user.password, str):
                try:
                    from werkzeug.security import check_password_hash
                    ok_pwd = check_password_hash(user.password, password)
                except Exception:
                    ok_pwd = (user.password == password)

        if not (user and ok_pwd):
            flash("Identifiants invalides.", "danger")
            return render_template("admin_login.html")

        is_admin = bool(getattr(user, "is_admin", False))
        role = (getattr(user, "user_type", "") or "").lower()
        if not (is_admin or role == "admin"):
            flash("Accès refusé : compte non administrateur.", "danger")
            return render_template("admin_login.html")

        login_user(user, remember=remember)
        return redirect(next_url)

    return render_template("admin_login.html")


# ─────────────────────────────────────────────────────────────
# Tableau de bord
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/")
@admin_required
def admin_dashboard():
    db, User, Professional, Appointment = _models()

    def _q_all(model, order_col=None, limit=None):
        q = model.query
        if order_col is not None:
            q = q.order_by(order_col)
        if limit:
            q = q.limit(limit)
        return q.all()

    def _q_count(model):
        return model.query.count()

    def _safe_sum(items, attr):
        s = 0.0
        for it in items:
            try:
                s += float(getattr(it, attr, 0) or 0)
            except Exception:
                pass
        return s

    pros = _q_all(Professional, order_col=getattr(Professional.id, "desc")() if hasattr(Professional.id, "desc") else None, limit=8)
    users = _q_all(User, order_col=User.id.desc(), limit=10)

    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = _q_all(Appointment, order_col=Appointment.id.desc(), limit=8)

    total_professionals = _q_count(Professional)
    total_users = _q_count(User)
    total_appointments = _q_count(Appointment)

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


# ─────────────────────────────────────────────────────────────
# Professionnels (liste / pending / classement / CRUD)
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/professionals")
@admin_required
def admin_products():
    db, User, Professional, Appointment = _models()

    pros = Professional.query.order_by(Professional.id.desc()).all()

    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = Appointment.query.order_by(Appointment.id.desc()).limit(8).all()

    return render_template(
        "admin_products.html",
        professionals=pros,
        users=User.query.order_by(User.id.desc()).limit(10).all(),
        appointments=appts,
        total_professionals=Professional.query.count(),
        total_users=User.query.count(),
        total_appointments=Appointment.query.count(),
        total_revenue=0.0,
    )


@admin_bp.route("/professionals/pending")
@admin_required
def pending_professionals():
    db, User, Professional, Appointment = _models()
    if hasattr(Professional, "status"):
        pros = Professional.query.filter(Professional.status == "en_attente").order_by(Professional.id.desc()).all()
    else:
        pros = []

    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = Appointment.query.order_by(Appointment.id.desc()).limit(8).all()

    return render_template(
        "admin_products.html",
        professionals=pros,
        users=User.query.order_by(User.id.desc()).limit(10).all(),
        appointments=appts,
        total_professionals=Professional.query.count(),
        total_users=User.query.count(),
        total_appointments=Appointment.query.count(),
        total_revenue=0.0,
    )


# Endpoint EXACT utilisé par tes templates et la sidebar
@admin_bp.route("/professionals/ranking", methods=["GET", "POST"])
@admin_required
def admin_professional_order():
    db, _, Professional, _ = _models()

    pros = Professional.query.order_by(Professional.id.desc()).all()

    if request.method == "POST":
        updated = 0
        if hasattr(Professional, "order_priority"):
            for p in pros:
                key = f"order_priority_{p.id}"
                if key in request.form:
                    try:
                        setattr(p, "order_priority", int(request.form.get(key) or 0))
                        updated += 1
                    except Exception:
                        pass
            if updated:
                db.session.commit()
                flash("Classement enregistré.", "success")
            else:
                flash("Aucune valeur de classement mise à jour.", "warning")
        else:
            flash("Le modèle Professional n’a pas de champ 'order_priority'.", "warning")
        return redirect(url_for("admin.admin_professional_order"))

    orders = {}
    if hasattr(Professional, "order_priority"):
        for p in pros:
            orders[p.id] = getattr(p, "order_priority") or 9999

    return render_template("admin_professional_order.html", professionals=pros, orders=orders)


@admin_bp.route("/professionals/<int:professional_id>/view")
@admin_required
def view_professional(professional_id: int):
    db, User, Professional, Appointment = _models()
    p = Professional.query.get_or_404(professional_id)

    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = Appointment.query.order_by(Appointment.id.desc()).limit(8).all()

    return render_template(
        "admin_products.html",
        professionals=[p],
        users=User.query.order_by(User.id.desc()).limit(10).all(),
        appointments=appts,
        total_professionals=Professional.query.count(),
        total_users=User.query.count(),
        total_appointments=Appointment.query.count(),
        total_revenue=0.0,
    )


# Endpoint explicitement attendu dans tes templates (product_id)
@admin_bp.route("/professionals/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id: int):
    db, User, Professional, Appointment = _models()
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

    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        appts = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(8).all()
    except Exception:
        appts = Appointment.query.order_by(Appointment.id.desc()).limit(8).all()

    return render_template(
        "admin_products.html",
        professionals=[p],
        users=User.query.order_by(User.id.desc()).limit(10).all(),
        appointments=appts,
        total_professionals=Professional.query.count(),
        total_users=User.query.count(),
        total_appointments=Appointment.query.count(),
        total_revenue=0.0,
    )


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

    return admin_products()


# ─────────────────────────────────────────────────────────────
# RDV / Commandes
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/orders")
@admin_required
def admin_orders():
    db, User, Professional, Appointment = _models()
    appt_date_col = getattr(Appointment, "appointment_date", None) or getattr(Appointment, "start_time", None) or getattr(Appointment, "created_at", None)
    try:
        orders = Appointment.query.order_by((appt_date_col or Appointment.id).desc()).limit(50).all()
    except Exception:
        orders = Appointment.query.order_by(Appointment.id.desc()).limit(50).all()

    return render_template(
        "admin_dashboard.html",
        professionals=Professional.query.order_by(Professional.id.desc()).limit(8).all(),
        users=User.query.order_by(User.id.desc()).limit(10).all(),
        appointments=orders,
        total_professionals=Professional.query.count(),
        total_users=User.query.count(),
        total_appointments=Appointment.query.count(),
        total_revenue=0.0,
    )


@admin_bp.route("/appointments")
@admin_required
def admin_appointments():
    return admin_orders()


# ─────────────────────────────────────────────────────────────
# Utilisateurs
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/users")
@admin_required
def admin_users():
    db, User, _, _ = _models()
    users = User.query.order_by(User.id.desc()).all()
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

    return admin_users()


# ─────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/logout")
def admin_logout():
    logout_user()
    flash("Déconnecté.", "success")
    return redirect(url_for("admin.admin_login"))


# ─────────────────────────────────────────────────────────────
# Healthcheck + textes mails réutilisables par app.py
# ─────────────────────────────────────────────────────────────
@admin_bp.route("/_health")
def _health():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


def _build_notif(kind: str, **kwargs) -> str:
    """
    Petit helper pour que app.py puisse réutiliser les mêmes textes.
    Personnalise au besoin.
    """
    if kind == "welcome_admin":
        return "Bienvenue dans l’administration Tighri."
    if kind == "appointment_created":
        return f"Un rendez-vous a été créé (id={kwargs.get('id','?')})."
    return "Notification Tighri."
