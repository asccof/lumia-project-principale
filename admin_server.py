# admin_server.py

from flask import Blueprint, render_template, render_template_string, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required
from sqlalchemy import func, or_        # ✅ or_ vient de SQLAlchemy (fix)
from jinja2 import TemplateNotFound     # ✅ pour fallback si template manquant
from datetime import datetime
from models import db, User, Professional, Appointment, ProfessionalAvailability, UnavailableSlot

admin_bp = Blueprint('admin', __name__, template_folder='templates')

# =========================
#  Classement des pros (utilisé par app.py)
# =========================
class ProfessionalOrder(db.Model):
    __tablename__ = 'professional_order'
    id = db.Column(db.Integer, primary_key=True)
    professional_id = db.Column(db.Integer, db.ForeignKey('professionals.id'), unique=True, nullable=False)
    order_priority = db.Column(db.Integer, nullable=False, default=999999)

# =========================
#  Guard admin
# =========================
from functools import wraps
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, 'is_admin', False):
            flash("Accès admin requis", "danger")
            return redirect(url_for('index'))
        return fn(*args, **kwargs)
    return wrapper

# =========================
#  Notifications (réutilisées par app.py)
# =========================
def _build_notif(kind: str, ap: Appointment, role: str = 'patient'):
    """
    Construit (subject, body) pour les emails.
    kind: 'pending' | 'accepted' | 'refused' | 'reminder'
    role: 'patient' | 'pro'
    """
    p = ap.professional or Professional.query.get(ap.professional_id)
    u = User.query.get(ap.patient_id) if ap.patient_id else None
    pro_name = p.name if p else "Professionnel"
    pat_name = u.username if u else "Patient"
    when = ap.appointment_date.strftime("%d/%m/%Y %H:%M") if ap.appointment_date else "—"
    brand = "Tighri"

    if role == 'patient':
        if kind == 'pending':
            return (f"[{brand}] Demande envoyée",
                    f"Bonjour {pat_name},\n\nVotre demande de rendez-vous du {when} "
                    f"avec {pro_name} a été envoyée.\nVous recevrez une confirmation bientôt.\n\n{brand}")
        if kind == 'accepted':
            return (f"[{brand}] Rendez-vous confirmé",
                    f"Bonjour {pat_name},\n\nVotre rendez-vous du {when} avec {pro_name} est CONFIRMÉ.\n\n{brand}")
        if kind == 'refused':
            return (f"[{brand}] Rendez-vous refusé",
                    f"Bonjour {pat_name},\n\nVotre demande du {when} avec {pro_name} a été refusée.\n\n{brand}")
        if kind == 'reminder':
            return (f"[{brand}] Rappel : rendez-vous demain",
                    f"Bonjour {pat_name},\n\nRappel : rendez-vous le {when} avec {pro_name}.\n\n{brand}")
    else:  # role == 'pro'
        if kind == 'pending':
            return (f"[{brand}] Nouvelle demande de rendez-vous",
                    f"Bonjour {pro_name},\n\nNouvelle demande pour le {when} de la part de {pat_name}.\n"
                    f"Merci de confirmer dans votre espace.\n\n{brand}")

    return (f"[{brand}] Notification", f"{brand}")

# =========================
#  Pages Admin
# =========================
@admin_bp.route('/', methods=['GET'])
@admin_required
def admin_home():
    pending_pros = (Professional.query
                    .filter(Professional.status == 'en_attente')
                    .order_by(Professional.created_at.desc())
                    .limit(20).all())
    valid_pros = (Professional.query
                  .filter(Professional.status == 'valide')
                  .order_by(Professional.created_at.desc())
                  .limit(20).all())
    users = User.query.order_by(User.id.desc()).limit(20).all()
    last_appts = Appointment.query.order_by(Appointment.id.desc()).limit(20).all()
    try:
        return render_template('admin_dashboard.html',
                               pending_pros=pending_pros,
                               valid_pros=valid_pros,
                               users=users,
                               last_appts=last_appts)
    except TemplateNotFound:
        # Fallback minimal si le template n’existe pas encore
        return render_template_string("""
        <div class="container p-4">
          <h3>Admin Dashboard (fallback)</h3>
          <p>Pending pros: {{ pending_pros|length }} — Valid pros: {{ valid_pros|length }}</p>
          <p>Users: {{ users|length }} — Last appts: {{ last_appts|length }}</p>
          <p>Crée le template <code>templates/admin_dashboard.html</code> pour une vue complète.</p>
        </div>
        """, pending_pros=pending_pros, valid_pros=valid_pros, users=users, last_appts=last_appts)

@admin_bp.route('/users', methods=['GET'])
@admin_required
def admin_users():
    q = request.args.get('q', '').strip()
    query = User.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))   # ✅ fix
    users = query.order_by(User.id.desc()).all()
    try:
        return render_template('admin_users.html', users=users, q=q)
    except TemplateNotFound:
        return render_template_string("""
        <div class="container p-4">
          <h3>Admin Users (fallback)</h3>
          <form method="get"><input name="q" value="{{ q }}" placeholder="Rechercher"><button>OK</button></form>
          <ul>
          {% for u in users %}
            <li>#{{u.id}} — {{u.username}} ({{u.email}}) — {{u.user_type}}
              <form style="display:inline" method="post" action="{{ url_for('admin.admin_delete_user', user_id=u.id) }}">
                <button onclick="return confirm('Supprimer utilisateur ?')">Supprimer</button>
              </form>
            </li>
          {% endfor %}
          </ul>
        </div>
        """, users=users, q=q)

@admin_bp.route('/professionals', methods=['GET'])
@admin_required
def admin_professionals():
    status = request.args.get('status', 'all')
    query = Professional.query
    if status in ('en_attente', 'valide', 'refuse'):
        query = query.filter(Professional.status == status)
    pros = query.order_by(Professional.created_at.desc()).all()
    try:
        return render_template('admin_professionals.html', professionals=pros, status=status)
    except TemplateNotFound:
        return render_template_string("""
        <div class="container p-4">
          <h3>Admin Pros (fallback)</h3>
          <p>Filtre: {{ status }}</p>
          <ul>
          {% for p in professionals %}
            <li>#{{p.id}} — {{p.name}} — {{p.status}}
              <form style="display:inline" method="post" action="{{ url_for('admin.admin_validate_professional', pro_id=p.id) }}">
                <button>Valider</button>
              </form>
              <form style="display:inline" method="post" action="{{ url_for('admin.admin_reject_professional', pro_id=p.id) }}">
                <button>Refuser</button>
              </form>
              <form style="display:inline" method="post" action="{{ url_for('admin.admin_delete_professional', pro_id=p.id) }}">
                <button onclick="return confirm('Supprimer pro ?')">Supprimer</button>
              </form>
            </li>
          {% endfor %}
          </ul>
        </div>
        """, professionals=pros, status=status)

# =========================
#  Actions Admin — Pros
# =========================
@admin_bp.route('/professionals/<int:pro_id>/validate', methods=['POST'])
@admin_required
def admin_validate_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = 'valide'
    db.session.commit()
    flash(f"Professionnel « {pro.name} » validé.", "success")
    return redirect(request.referrer or url_for('admin.admin_professionals'))

@admin_bp.route('/professionals/<int:pro_id>/reject', methods=['POST'])
@admin_required
def admin_reject_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    pro.status = 'refuse'
    db.session.commit()
    flash(f"Professionnel « {pro.name} » refusé.", "warning")
    return redirect(request.referrer or url_for('admin.admin_professionals'))

@admin_bp.route('/professionals/<int:pro_id>/delete', methods=['POST'])
@admin_required
def admin_delete_professional(pro_id):
    pro = Professional.query.get_or_404(pro_id)
    Appointment.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    ProfessionalAvailability.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    UnavailableSlot.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    ProfessionalOrder.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
    db.session.delete(pro)
    db.session.commit()
    flash("Profil professionnel supprimé.", "success")
    return redirect(request.referrer or url_for('admin.admin_professionals'))

# =========================
#  Action Admin — Suppression d'utilisateur
# =========================
@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.user_type == 'professional':
        pro = Professional.query.filter_by(name=user.username).first()
        if pro:
            Appointment.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalAvailability.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            UnavailableSlot.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            ProfessionalOrder.query.filter_by(professional_id=pro.id).delete(synchronize_session=False)
            db.session.delete(pro)

    if user.user_type == 'patient':
        Appointment.query.filter_by(patient_id=user.id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()
    flash("Utilisateur supprimé.", "success")
    return redirect(request.referrer or url_for('admin.admin_users'))

# =========================
#  RDV — Mise à jour statut (compat logs)
# =========================
@admin_bp.route('/orders/<int:appointment_id>/status', methods=['POST'])
@admin_required
def admin_update_order_status(appointment_id):
    new_status = (request.form.get('status') or '').strip()  # 'confirme' | 'annule' | 'en_attente'
    ap = Appointment.query.get_or_404(appointment_id)

    if new_status not in ('confirme', 'annule', 'en_attente'):
        return jsonify({'ok': False, 'error': 'status invalide'}), 400

    ap.status = new_status
    db.session.commit()
    flash(f"Rendez-vous #{ap.id} → {new_status}", "success")
    return jsonify({'ok': True})
