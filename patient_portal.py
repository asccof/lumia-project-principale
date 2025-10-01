# patient_portal.py — Contrat-fix : ajouts isolés, compatibles app.py/models.py actuels
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from datetime import datetime

from models import (
    db, User, Professional, Appointment,
    ExerciseAssignment, ExerciseProgress, ExerciseItem,
    MessageThread, Message, TherapeuticJournal, JournalEntry,
)

patient_bp = Blueprint("patient_portal", __name__, template_folder="templates")

def _ensure_patient():
    if not (current_user.is_authenticated and current_user.user_type in ("patient", "professional")):
        abort(403)

@patient_bp.route("/", methods=["GET"])
@login_required
def space():
    _ensure_patient()
    # RDV récents et à venir
    if current_user.user_type == "professional":
        pro = Professional.query.filter_by(name=current_user.username).first()
        appts = Appointment.query.filter_by(professional_id=pro.id).order_by(Appointment.appointment_date.desc()).limit(10).all() if pro else []
    else:
        appts = Appointment.query.filter_by(patient_id=current_user.id).order_by(Appointment.appointment_date.desc()).limit(10).all()
    return render_template("patient/space.html", appointments=appts)

@patient_bp.route("/exercises", methods=["GET","POST"])
@login_required
def exercises():
    _ensure_patient()
    if current_user.user_type == "professional":
        # un pro peut se voir attribuer ses propres exos pour tests, sinon vide
        assigns = ExerciseAssignment.query.join(ExerciseItem).order_by(ExerciseAssignment.created_at.desc()).limit(50).all()
    else:
        assigns = ExerciseAssignment.query.filter_by(patient_user_id=current_user.id).order_by(ExerciseAssignment.created_at.desc()).all()
    return render_template("patient/exercises.html", assignments=assigns)

@patient_bp.route("/exercises/<int:assignment_id>", methods=["GET","POST"])
@login_required
def exercise_detail(assignment_id: int):
    _ensure_patient()
    assign = ExerciseAssignment.query.get_or_404(assignment_id)
    if current_user.user_type == "patient" and assign.patient_user_id != current_user.id:
        abort(403)

    if request.method == "POST":
        resp_text = (request.form.get("response_text") or "").strip()
        progress = ExerciseProgress(
            assignment_id=assign.id, progress_percent=100 if resp_text else 0,
            response_text=resp_text
        )
        db.session.add(progress); db.session.commit()
        flash("Réponse enregistrée.", "success")
        return redirect(url_for("patient_portal.exercises"))

    return render_template("patient/exercise_detail.html", assign=assign)

@patient_bp.route("/visio/<int:appointment_id>", methods=["GET"])
@login_required
def visio(appointment_id: int):
    _ensure_patient()
    ap = Appointment.query.get_or_404(appointment_id)
    # Autorisation : le patient de ce RDV ou le pro
    is_patient = (current_user.user_type == "patient" and ap.patient_id == current_user.id)
    is_pro = (current_user.user_type == "professional" and Professional.query.filter_by(id=ap.professional_id, name=current_user.username).first() is not None)
    if not (is_patient or is_pro):
        abort(403)
    # simple page de pré-réunion + bouton “Rejoindre Google Meet”
    return render_template("patient/visio_gate.html", ap=ap)
