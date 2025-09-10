# admin_server.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime

# ⚠️ Utiliser **la même** instance db et modèles que le reste de l’app
from models import db, User, Professional, Appointment

admin_bp = Blueprint("admin", __name__, template_folder="templates")

# --------------------------------------------------------------------
# ProfessionalOrder
# - Si le modèle existe déjà dans models.py → on l’importe.
# - Sinon on le déclare ici, sans requêtes au niveau module.
# --------------------------------------------------------------------
try:
    from models import ProfessionalOrder  # déjà défini chez toi ? on réutilise
except Exception:
    class ProfessionalOrder(db.Model):
        __tablename__ = "professional_order"
        # extend_existing: évite "Table already defined" si MetaData l’a déjà
        __table_args__ = {"extend_existing": True}

        id = db.Column(db.Integer, primary_key=True)
        professional_id = db.Column(
            db.Integer,
            db.ForeignKey("professionals.id"),
            nullable=False,
            unique=True,
            index=True,
        )
        order_priority = db.Column(db.Integer, nullable=False, default=999_999)

        professional = db.relationship(
            "Professional",
            backref=db.backref("order_row", uselist=False),
        )

        def __repr__(self) -> str:
            return f"<ProfessionalOrder pro_id={self.professional_id} order={self.order_priority}>"

# --------------------------------------------------------------------
# Notifications (réutilisées par app.py)
# --------------------------------------------------------------------
def _build_notif(kind: str, ap: Appointment, role: str = "patient"):
    """
    Retourne (subject, body) pour email. Utilisé aussi par app.py.
    kind: 'pending' | 'accepted' | 'refused' | 'reminder'
    role: 'patient' | 'pro'
    """
    pro = ap.professional if hasattr(ap, "professional") and ap.professional else Professional.query.get(ap.professional_id)
    pat = User.query.get(ap.patient_id) if ap and ap.patient_id else None

    when = ap.appointment_date.strftime("%Y-%m-%d %H:%M") if ap and ap.appointment_date else "date à préciser"
    pro_name = pro.name if pro else "le professionnel"
    pat_name = pat.username if pat else "le patient"

    if role == "pro":
        # message envoyé au pro
        if kind == "pending":
            subject = f"[Tighri] Nouvelle demande de RDV - {pat_name}"
            body = (
                f"Bonjour,\n\n"
                f"Vous avez reçu une nouvelle demande de rendez-vous de la part de {pat_name} pour le {when}.\n"
                f"Type: {ap.consultation_type or 'cabinet'}\n\n"
                f"Connectez-vous pour accepter ou refuser.\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "accepted":
            subject = f"[Tighri] RDV confirmé - {pat_name} le {when}"
            body = (
                f"Bonjour,\n\n"
                f"Le rendez-vous avec {pat_name} est confirmé pour le {when}.\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "refused":
            subject = f"[Tighri] RDV refusé - {pat_name} ({when})"
            body = (
                f"Bonjour,\n\n"
                f"Vous avez refusé la demande de rendez-vous avec {pat_name} ({when}).\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "reminder":
            subject = f"[Tighri] Rappel RDV demain - {pat_name} ({when})"
            body = (
                f"Bonjour,\n\n"
                f"Rappel : rendez-vous prévu demain avec {pat_name} ({when}).\n\n"
                f"Cordialement,\nTighri"
            )
        else:
            subject = "[Tighri] Notification"
            body = "Bonjour,\n\nNotification.\n\nCordialement,\nTighri"
    else:
        # message envoyé au patient (par défaut)
        if kind == "pending":
            subject = f"[Tighri] Demande envoyée à {pro_name}"
            body = (
                f"Bonjour,\n\n"
                f"Votre demande de rendez-vous avec {pro_name} pour le {when} a bien été envoyée.\n"
                f"Vous recevrez un e-mail de confirmation dès que le professionnel l’acceptera.\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "accepted":
            subject = f"[Tighri] RDV confirmé avec {pro_name} - {when}"
            body = (
                f"Bonjour,\n\n"
                f"Votre rendez-vous avec {pro_name} est confirmé pour le {when}.\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "refused":
            subject = f"[Tighri] RDV refusé - {pro_name}"
            body = (
                f"Bonjour,\n\n"
                f"Votre demande de rendez-vous avec {pro_name} a été refusée.\n"
                f"Vous pouvez choisir un autre créneau ou un autre professionnel sur Tighri.\n\n"
                f"Cordialement,\nTighri"
            )
        elif kind == "reminder":
            subject = f"[Tighri] Rappel : RDV demain avec {pro_name}"
            body = (
                f"Bonjour,\n\n"
                f"Rappel : vous avez un rendez-vous demain avec {pro_name} ({when}).\n\n"
                f"Cordialement,\nTighri"
            )
        else:
            subject = "[Tighri] Notification"
            body = "Bonjour,\n\nNotification.\n\nCordialement,\nTighri"

    return subject, body

# --------------------------------------------------------------------
# VUES ADMIN — pas de DB au niveau module, seulement dans les fonctions
# --------------------------------------------------------------------
@admin_bp.route("/")
def admin_home():
    return render_template("admin/index.html")

@admin_bp.route("/order", methods=["GET", "POST"])
def admin_order():
    """
    Page simple pour classer les pros :
    - GET : liste des pros valides + ordre courant
    - POST : enregistre les priorités envoyées (form name='order_{pro_id}')
    """
    if request.method == "POST":
        # On boucle sur tous les pros envoyés dans le formulaire
        for key, value in request.form.items():
            if not key.startswith("order_"):
                continue
            try:
                pro_id = int(key.split("_", 1)[1])
                prio = int(value.strip() or "999999")
            except Exception:
                continue

            row = ProfessionalOrder.query.filter_by(professional_id=pro_id).first()
            if not row:
                row = ProfessionalOrder(professional_id=pro_id, order_priority=prio)
                db.session.add(row)
            else:
                row.order_priority = prio

        db.session.commit()
        flash("Classement mis à jour.", "success")
        return redirect(url_for("admin.admin_order"))

    pros = (
        Professional.query.filter_by(status="valide")
        .order_by(Professional.created_at.desc(), Professional.id.desc())
        .all()
    )
    # Dictionnaire pro_id -> prio
    current = {
        r.professional_id: r.order_priority
        for r in ProfessionalOrder.query.all()
    }
    return render_template("admin/order.html", professionals=pros, order=current)
