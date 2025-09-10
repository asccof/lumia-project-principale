# admin_server.py
from __future__ import annotations

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify
)
from flask_login import current_user, login_user, logout_user
from werkzeug.security import check_password_hash
from datetime import datetime, date
from sqlalchemy import or_
import os

# --- Modèles et DB ---
from models import (
    db, User, Professional, Appointment
)

# --- Compatibilité de noms de modèles entre anciennes/nouvelles versions -----
# ProfessionalAvailability  ⇄  ProfessionalAvailabilityWindow
try:
    from models import ProfessionalAvailability  # nouveau/nom standard
except Exception:
    from models import ProfessionalAvailabilityWindow as ProfessionalAvailability  # alias vers l'ancien nom

# UnavailableSlot (au cas où certains projets l’ont nommé "UnavailableTimeSlot")
try:
    from models import UnavailableSlot
except Exception:
    try:
        from models import UnavailableTimeSlot as UnavailableSlot  # alias alternative
    except Exception:
        UnavailableSlot = None  # type: ignore

# Modèles optionnels (si non présents, on garde l'admin fonctionnel)
try:
    from models import Review
except Exception:
    Review = None  # type: ignore

try:
    from models import SocialLink
except Exception:
    SocialLink = None  # type: ignore


# =============================================================================
# 1) Modèle ProfessionalOrder (classement des pros pour la home)
# =============================================================================
class ProfessionalOrder(db.Model):
    __tablename__ = "professional_order"
    professional_id = db.Column(db.Integer, db.ForeignKey("professionals.id"), primary_key=True)
    order_priority  = db.Column(db.Integer, nullable=False, default=9999)

    professional = db.relationship("Professional", backref=db.backref("order_entry", uselist=False))

    def __repr__(self) -> str:
        return f"<ProfessionalOrder pro_id={self.professional_id} order={self.order_priority}>"

# =============================================================================
# 2) Notifications e-mail – utilisées par app.py (exportées ici)
# =============================================================================
def _build_notif(kind, ap: Appointment, role: str = "patient"):
    """
    Retourne (subject, body) pour emails.
    kind: 'pending'|'accepted'|'refused'|'reminder'
    role: 'patient'|'pro'
    """
    pro = getattr(ap, "professional", None)
    patient_user = getattr(ap, "patient", None)
    pro_name = getattr(pro, "name", None) or "Professionnel"
    patient_name = getattr(patient_user, "username", None) or "Patient"

    try:
        dt = ap.appointment_date.strftime("%d/%m/%Y %H:%M") if getattr(ap, "appointment_date", None) else ""
    except Exception:
        dt = ""
    type_txt = getattr(ap, "consultation_type", None) or "cabinet"

    if kind == "pending":
        if role == "pro":
            subject = f"Nouvelle demande de rendez-vous – {patient_name}"
            body = (
                f"Bonjour {pro_name},\n\n"
                f"Vous avez une nouvelle demande de rendez-vous de la part de {patient_name} "
                f"pour le {dt} ({type_txt}).\n\n"
                f"Merci de confirmer ou refuser depuis votre espace professionnel."
            )
        else:
            subject = f"Demande de rendez-vous envoyée – {pro_name}"
            body = (
                f"Bonjour {patient_name},\n\n"
                f"Votre demande de rendez-vous avec {pro_name} pour le {dt} ({type_txt}) a bien été envoyée. "
                f"Vous recevrez un email dès que le professionnel confirmera."
            )
    elif kind == "accepted":
        subject = f"Rendez-vous confirmé – {dt}"
        body = (
            f"Bonjour {patient_name},\n\n"
            f"Votre rendez-vous avec {pro_name} pour le {dt} ({type_txt}) est confirmé."
        )
    elif kind == "refused":
        subject = "Rendez-vous non disponible"
        body = (
            f"Bonjour {patient_name},\n\n"
            f"Le rendez-vous demandé avec {pro_name} le {dt} ({type_txt}) n’est pas disponible. "
            f"Vous pouvez choisir un autre créneau depuis votre espace."
        )
    elif kind == "reminder":
        subject = f"Rappel de rendez-vous – {dt}"
        body = (
            f"Bonjour {patient_name},\n\n"
            f"Ceci est un rappel pour votre rendez-vous avec {pro_name} le {dt} ({type_txt})."
        )
    else:
        subject = "Notification Tighri"
        body = "Bonjour,\n\nVous avez une notification concernant votre rendez-vous."
    return subject, body


# =============================================================================
# 3) Blueprint Admin + garde de sécurité is_admin
# =============================================================================
admin_bp = Blueprint("admin", __name__, template_folder="templates")

@admin_bp.before_app_request
def _admin_protect():
    """Protéger les routes /admin/* : admin requis (sauf /admin/login)."""
    if request.path.startswith("/admin") and not request.path.startswith("/admin/login"):
        # Autoriser assets statiques
        if request.path.startswith("/admin/static"):
            return
        # Autoriser redirection quand pas connecté
        if not hasattr(current_user, "is_authenticated") or not current_user.is_authenticated:
            return redirect(url_for("admin.admin_login"))
        if not getattr(current_user, "is_admin", False):
            flash("Accès administrateur requis.", "danger")
            return redirect(url_for("index"))


# =============================================================================
# 4) Authentification Admin
# =============================================================================
@admin_bp.route("/login", methods=["GET", "POST"], endpoint="admin_login")
def admin_login():
    if request.method == "POST":
        username_or_email = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        user = User.query.filter(
            or_(User.username == username_or_email, User.email == username_or_email.lower())
        ).first()
        if user and user.is_admin and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            flash("Bienvenue dans l’administration.", "success")
            return redirect(url_for("admin.admin_dashboard"))
        flash("Identifiants invalides ou droits insuffisants.", "danger")

    return render_template("admin_login.html")

@admin_bp.route("/logout", endpoint="admin_logout")
def admin_logout():
    logout_user()
    return redirect(url_for("admin.admin_login"))


# =============================================================================
# 5) Dashboard
# =============================================================================
@admin_bp.route("/", endpoint="admin_dashboard")
def admin_dashboard():
    stats = {
        "users": User.query.count(),
        "pros": Professional.query.count(),
        "appointments": Appointment.query.count(),
        "pending_pros": Professional.query.filter_by(status="en_attente").count(),
    }
    return render_template("admin_dashboard.html", stats=stats)


# =============================================================================
# 6) Professionnels (liste, vue, CRUD léger, statut, disponibilité)
# =============================================================================
@admin_bp.route("/products", endpoint="admin_products")
def admin_products():
    """ATTENTION : dans certains templates, 'products' = professionnels (héritage de nom)."""
    professionals = Professional.query.order_by(Professional.id.desc()).all()
    return render_template("admin_products.html", professionals=professionals)

@admin_bp.route("/professionals/pending", endpoint="pending_professionals")
def pending_professionals():
    professionals = Professional.query.filter_by(status="en_attente").order_by(Professional.id.desc()).all()
    return render_template("pending_professionals.html", professionals=professionals)

@admin_bp.route("/products/add", methods=["GET", "POST"], endpoint="admin_add_product")
def admin_add_product():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        specialty = (request.form.get("specialty") or "").strip()
        location = (request.form.get("location") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()
        latitude = (request.form.get("latitude") or "").strip()
        longitude = (request.form.get("longitude") or "").strip()
        fee = request.form.get("consultation_fee") or "0"
        duration = request.form.get("consultation_duration_minutes") or "45"
        buffer_m = request.form.get("buffer_between_appointments_minutes") or "15"
        exp_years = request.form.get("experience_years") or "0"
        description = (request.form.get("description") or "").strip()
        image_url = (request.form.get("image_url") or "").strip()

        # types de consultation (checkbox multiples "consultation_types")
        types = request.form.getlist("consultation_types")
        types_csv = ",".join(sorted(set([t.strip() for t in types if t.strip()])))

        # réseaux sociaux
        facebook_url  = (request.form.get("facebook_url") or "").strip() or None
        instagram_url = (request.form.get("instagram_url") or "").strip() or None
        tiktok_url    = (request.form.get("tiktok_url") or "").strip() or None
        youtube_url   = (request.form.get("youtube_url") or "").strip() or None
        social_links_approved = bool(request.form.get("social_links_approved"))

        try:
            pro = Professional(
                name=name,
                specialty=specialty,
                location=location,
                address=address or None,
                latitude=float(latitude) if latitude else None,
                longitude=float(longitude) if longitude else None,
                phone=phone or None,
                consultation_fee=float(str(fee).replace(",", ".")),
                consultation_duration_minutes=int(duration),
                buffer_between_appointments_minutes=int(buffer_m),
                experience_years=int(exp_years),
                description=description or None,
                image_url=image_url or None,
                consultation_types=types_csv or "cabinet",
                availability="disponible",
                facebook_url=facebook_url,
                instagram_url=instagram_url,
                tiktok_url=tiktok_url,
                youtube_url=youtube_url,
                social_links_approved=social_links_approved,
                status="valide",
            )
            db.session.add(pro)
            db.session.commit()
            flash("Professionnel ajouté.", "success")
            return redirect(url_for("admin.admin_products"))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur: {e}", "danger")

    return render_template("add_product.html")

@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"], endpoint="admin_edit_product")
def admin_edit_product(product_id):
    pro = Professional.query.get_or_404(product_id)
    if request.method == "POST":
        pro.name = (request.form.get("name") or pro.name).strip()
        pro.specialty = (request.form.get("specialty") or pro.specialty or "").strip()
        pro.location = (request.form.get("location") or pro.location or "").strip()
        pro.phone = (request.form.get("phone") or pro.phone or "").strip() or None
        pro.address = (request.form.get("address") or getattr(pro, "address", "") or "").strip() or None

        lat = (request.form.get("latitude") or "").strip()
        lng = (request.form.get("longitude") or "").strip()
        pro.latitude = float(lat) if lat else None
        pro.longitude = float(lng) if lng else None

        fee = request.form.get("consultation_fee") or ""
        pro.consultation_fee = float(str(fee).replace(",", ".")) if fee else pro.consultation_fee

        dur = request.form.get("consultation_duration_minutes") or ""
        buf = request.form.get("buffer_between_appointments_minutes") or ""
        pro.consultation_duration_minutes = int(dur) if dur else getattr(pro, "consultation_duration_minutes", 45)
        pro.buffer_between_appointments_minutes = int(buf) if buf else getattr(pro, "buffer_between_appointments_minutes", 15)

        pro.experience_years = int(request.form.get("experience_years") or pro.experience_years or 0)
        pro.description = (request.form.get("description") or pro.description or "").strip() or None

        # image
        image_url = (request.form.get("image_url") or "").strip()
        if image_url:
            pro.image_url = image_url

        # types consultation
        types = request.form.getlist("consultation_types")
        types_csv = ",".join(sorted(set([t.strip() for t in types if t.strip()])))
        pro.consultation_types = types_csv or pro.consultation_types

        # disponibilité & statut
        pro.availability = (request.form.get("availability") or pro.availability or "disponible").strip()
        pro.status = (request.form.get("status") or pro.status or "en_attente").strip()

        # réseaux sociaux
        pro.facebook_url  = (request.form.get("facebook_url") or pro.facebook_url or "").strip() or None
        pro.instagram_url = (request.form.get("instagram_url") or pro.instagram_url or "").strip() or None
        pro.tiktok_url    = (request.form.get("tiktok_url") or pro.tiktok_url or "").strip() or None
        pro.youtube_url   = (request.form.get("youtube_url") or pro.youtube_url or "").strip() or None
        pro.social_links_approved = bool(request.form.get("social_links_approved")) or False

        try:
            db.session.commit()
            flash("Profil mis à jour.", "success")
            return redirect(url_for("admin.admin_products"))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur: {e}", "danger")

    return render_template("edit_product.html", professional=pro)

@admin_bp.route("/products/<int:product_id>/delete", endpoint="delete_professional")
def delete_professional(product_id):
    pro = Professional.query.get_or_404(product_id)
    db.session.delete(pro)
    db.session.commit()
    flash("Professionnel supprimé.", "success")
    return redirect(url_for("admin.admin_products"))

# alias utilisés par certains templates
@admin_bp.route("/professionals", endpoint="admin_professionals")
def admin_professionals():
    professionals = Professional.query.order_by(Professional.id.desc()).all()
    return render_template("admin.html", professionals=professionals)

@admin_bp.route("/professionals/<int:professional_id>/view", endpoint="view_professional")
def view_professional(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    appointments = Appointment.query.filter_by(professional_id=professional.id).order_by(Appointment.appointment_date.desc()).limit(25).all()
    return render_template("view_professional.html", professional=professional, appointments=appointments)

# Validation / Rejet (AJAX)
@admin_bp.route("/professionals/<int:professional_id>/validate", methods=["POST"], endpoint="validate_professional")
def validate_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    p.status = "valide"
    db.session.commit()
    return jsonify({"success": True})

@admin_bp.route("/professionals/<int:professional_id>/reject", methods=["POST"], endpoint="reject_professional")
def reject_professional(professional_id):
    p = Professional.query.get_or_404(professional_id)
    p.status = "rejete"
    db.session.commit()
    return jsonify({"success": True})

# Disponibilités (admin)
@admin_bp.route("/professionals/<int:professional_id>/availability", methods=["GET", "POST"], endpoint="admin_professional_availability")
def admin_professional_availability(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        ProfessionalAvailability.query.filter_by(professional_id=professional.id).delete()

        def add_window(day, s, e, flag):
            s = (s or "").strip()
            e = (e or "").strip()
            if flag and s and e:
                db.session.add(ProfessionalAvailability(
                    professional_id=professional.id,
                    day_of_week=day,
                    start_time=s,
                    end_time=e,
                    is_available=True
                ))

        for d in range(7):
            base = request.form.get(f"available_{d}") == "on"
            add_window(d, request.form.get(f"start_time_{d}", ""), request.form.get(f"end_time_{d}", ""), base)
            add_window(d, request.form.get(f"start_time_{d}_2", ""), request.form.get(f"end_time_{d}_2", ""),
                       request.form.get(f"available_{d}_2") == "on" or base)
            add_window(d, request.form.get(f"start_time_{d}_3", ""), request.form.get(f"end_time_{d}_3", ""),
                       request.form.get(f"available_{d}_3") == "on" or base)

        db.session.commit()
        flash("Disponibilités enregistrées.", "success")
        return redirect(url_for("admin.admin_professional_availability", professional_id=professional.id))

    avs = ProfessionalAvailability.query.filter_by(professional_id=professional.id).all()
    windows_by_day = {d: [] for d in range(7)}
    for a in avs:
        windows_by_day[a.day_of_week].append(a)
    return render_template("admin_professional_availability.html",
                           professional=professional,
                           windows_by_day=windows_by_day)

# Indisponibilités (admin)
@admin_bp.route("/professionals/<int:professional_id>/unavailable-slots", methods=["GET", "POST"], endpoint="admin_professional_unavailable_slots")
def admin_professional_unavailable_slots(professional_id):
    professional = Professional.query.get_or_404(professional_id)
    if request.method == "POST":
        date_str = request.form.get("date", "")
        start_time = request.form.get("start_time", "")
        end_time = request.form.get("end_time", "")
        reason = (request.form.get("reason") or "").strip()
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            flash("Date invalide", "danger")
            return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))
        if d < date.today():
            flash("Impossible d’ajouter dans le passé.", "warning")
            return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))

        if UnavailableSlot is None:
            flash("Le modèle UnavailableSlot est indisponible.", "danger")
            return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))

        slot = UnavailableSlot(
            professional_id=professional.id,
            date=d,
            start_time=start_time,
            end_time=end_time,
            reason=reason or None
        )
        db.session.add(slot)
        db.session.commit()
        flash("Créneau ajouté.", "success")
        return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))

    slots = []
    if UnavailableSlot is not None:
        slots = UnavailableSlot.query.filter_by(professional_id=professional.id).order_by(UnavailableSlot.date.desc()).all()

    return render_template("admin_professional_unavailable_slots.html",
                           professional=professional, unavailable_slots=slots)

@admin_bp.route("/professionals/<int:professional_id>/unavailable-slots/<int:slot_id>/delete",
                methods=["POST"], endpoint="admin_delete_unavailable_slot")
def admin_delete_unavailable_slot(professional_id, slot_id):
    professional = Professional.query.get_or_404(professional_id)
    if UnavailableSlot is None:
        flash("Le modèle UnavailableSlot est indisponible.", "danger")
        return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))
    slot = UnavailableSlot.query.get_or_404(slot_id)
    if slot.professional_id != professional.id:
        flash("Accès non autorisé.", "danger")
        return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))
    db.session.delete(slot)
    db.session.commit()
    flash("Créneau supprimé.", "success")
    return redirect(url_for("admin.admin_professional_unavailable_slots", professional_id=professional.id))


# =============================================================================
# 7) Rendez-vous (liste + MAJ statut)
# =============================================================================
@admin_bp.route("/appointments", endpoint="admin_appointments")
def admin_appointments():
    appointments = Appointment.query.order_by(Appointment.appointment_date.desc()).limit(500).all()
    return render_template("admin_appointments.html", appointments=appointments)

@admin_bp.route("/appointments/<int:appointment_id>/status", methods=["POST"], endpoint="update_appointment_status")
def update_appointment_status(appointment_id):
    ap = Appointment.query.get_or_404(appointment_id)
    payload = request.get_json(silent=True) or {}
    status = (payload.get("status") or "").strip()
    if status not in {"confirme", "annule", "en_attente"}:
        return jsonify({"success": False, "message": "Statut invalide"}), 400
    ap.status = status
    db.session.commit()
    return jsonify({"success": True})


# =============================================================================
# 8) Utilisateurs (liste / ajouter / éditer / supprimer)
# =============================================================================
@admin_bp.route("/users", endpoint="admin_users")
def admin_users():
    users = User.query.order_by(User.id.desc()).limit(1000).all()
    return render_template("admin_users.html", users=users)

@admin_bp.route("/users/add", methods=["GET", "POST"], endpoint="add_user")
def add_user():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        is_admin = bool(request.form.get("is_admin"))

        if not username or not email or not password:
            flash("Champs requis manquants.", "danger")
            return redirect(url_for("admin.add_user"))

        if User.query.filter_by(username=username).first():
            flash("Nom d’utilisateur déjà pris.", "danger")
            return redirect(url_for("admin.add_user"))
        if User.query.filter_by(email=email).first():
            flash("Email déjà enregistré.", "danger")
            return redirect(url_for("admin.add_user"))

        from werkzeug.security import generate_password_hash
        u = User(username=username, email=email,
                 password_hash=generate_password_hash(password),
                 is_admin=is_admin,
                 user_type="patient")
        db.session.add(u)
        db.session.commit()
        flash("Utilisateur ajouté.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template("add_user.html")

@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"], endpoint="edit_user")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == "POST":
        username = (request.form.get("username") or user.username).strip()
        email = (request.form.get("email") or user.email).strip().lower()
        new_pass = (request.form.get("password") or "").strip()
        user_type = (request.form.get("user_type") or user.user_type or "patient").strip()
        phone = (request.form.get("phone") or user.phone or "").strip() or None
        is_admin = bool(request.form.get("is_admin"))

        # unicité minimale
        collision = User.query.filter(User.id != user.id, User.username == username).first()
        if collision:
            flash("Nom d’utilisateur déjà pris.", "danger")
            return redirect(url_for("admin.edit_user", user_id=user.id))
        collision = User.query.filter(User.id != user.id, User.email == email).first()
        if collision:
            flash("Email déjà utilisé.", "danger")
            return redirect(url_for("admin.edit_user", user_id=user.id))

        user.username = username
        user.email = email
        user.user_type = user_type
        user.is_admin = is_admin
        user.phone = phone

        if new_pass:
            from werkzeug.security import generate_password_hash
            user.password_hash = generate_password_hash(new_pass)

        # Conversion vers professionnel : créer/mettre à jour un profil si besoin
        if user_type == "professional":
            pro = Professional.query.filter_by(name=user.username).first()
            if not pro:
                pro = Professional(
                    name=user.username,
                    description="Profil en cours de complétion.",
                    specialty="Psychologue",
                    location="Casablanca",
                    availability="disponible",
                    consultation_types="cabinet",
                    status="en_attente",
                    phone=user.phone or None
                )
                db.session.add(pro)

        db.session.commit()
        flash("Utilisateur modifié.", "success")
        return redirect(url_for("admin.admin_users"))

    return render_template("edit_user.html", user=user)

@admin_bp.route("/users/<int:user_id>/delete", endpoint="delete_user")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(url_for("admin.admin_users"))


# =============================================================================
# 9) Avis (pending/approve/reject/delete) — robustes si Review absent
# =============================================================================
@admin_bp.route("/reviews/pending", endpoint="admin_reviews_pending")
def admin_reviews_pending():
    if Review is None:
        reviews = []
        total_approved = total_rejected = 0
    else:
        reviews = Review.query.filter_by(approved=False).order_by(Review.created_at.desc()).all()
        total_approved = Review.query.filter_by(approved=True).count()
        total_rejected = 0  # adaptez si vous avez un champ/état
    return render_template("admin_reviews_pending.html",
                           reviews=reviews,
                           total_approved=total_approved,
                           total_rejected=total_rejected)

@admin_bp.route("/reviews", endpoint="admin_reviews")
def admin_reviews():
    if Review is None:
        return render_template("admin_reviews.html", reviews=[], status="all")
    status = request.args.get("status", "pending")
    q = Review.query.order_by(Review.created_at.desc())
    if status == "pending":
        q = q.filter_by(approved=False)
    elif status == "approved":
        q = q.filter_by(approved=True)
    reviews = q.all()
    return render_template("admin_reviews.html", reviews=reviews, status=status)

@admin_bp.route("/reviews/<int:review_id>/<action>", methods=["POST"], endpoint="admin_reviews_action")
def admin_reviews_action(review_id, action):
    if Review is None:
        flash("Module d’avis indisponible.", "warning")
        return redirect(url_for("admin.admin_reviews_pending"))
    r = Review.query.get_or_404(review_id)
    if action == "approve":
        r.approved = True
        db.session.commit()
        flash("Avis approuvé.", "success")
    elif action == "reject":
        db.session.delete(r)
        db.session.commit()
        flash("Avis rejeté (supprimé).", "success")
    elif action == "delete":
        db.session.delete(r)
        db.session.commit()
        flash("Avis supprimé.", "success")
    else:
        flash("Action inconnue.", "danger")
    return redirect(url_for("admin.admin_reviews_pending"))


# =============================================================================
# 10) Liens sociaux (pending/approve/reject) — robustes si SocialLink absent
# =============================================================================
@admin_bp.route("/social/pending", endpoint="admin_social_pending")
def admin_social_pending():
    if SocialLink is None:
        links = []
    else:
        links = SocialLink.query.filter_by(approved=False).order_by(SocialLink.created_at.desc()).all()
    return render_template("admin_social_pending.html", links=links)

@admin_bp.route("/social/<int:link_id>/<action>", methods=["POST"], endpoint="admin_social_action")
def admin_social_action(link_id, action):
    if SocialLink is None:
        flash("Module liens sociaux indisponible.", "warning")
        return redirect(url_for("admin.admin_social_pending"))
    link = SocialLink.query.get_or_404(link_id)
    if action == "approve":
        link.approved = True
        db.session.commit()
        flash("Lien approuvé.", "success")
    elif action == "reject":
        db.session.delete(link)
        db.session.commit()
        flash("Lien rejeté (supprimé).", "success")
    else:
        flash("Action inconnue.", "danger")
    return redirect(url_for("admin.admin_social_pending"))


# =============================================================================
# 11) Classement “ProfessionalOrder” – page et sauvegarde
# =============================================================================
@admin_bp.route("/professional-order", methods=["GET", "POST"], endpoint="admin_professional_order")
def admin_professional_order():
    professionals = Professional.query.order_by(Professional.name.asc()).all()

    if request.method == "POST":
        for p in professionals:
            key = f"order_priority_{p.id}"
            val_raw = request.form.get(key)
            if val_raw is None:
                continue
            try:
                val = int(val_raw)
            except ValueError:
                val = 9999
            entry = ProfessionalOrder.query.filter_by(professional_id=p.id).first()
            if not entry:
                entry = ProfessionalOrder(professional_id=p.id, order_priority=val)
                db.session.add(entry)
            else:
                entry.order_priority = val
        db.session.commit()
        flash("Classement enregistré.", "success")
        return redirect(url_for("admin.admin_professional_order"))

    orders = {po.professional_id: po.order_priority for po in ProfessionalOrder.query.all()}
    return render_template("admin_professional_order.html",
                           professionals=professionals,
                           orders=orders)
