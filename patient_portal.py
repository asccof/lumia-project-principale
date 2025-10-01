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
# === Messagerie — boîte patient ===
@patient_bp.route("/messages", methods=["GET"])
@login_required
def messages_inbox():
    _ensure_patient()
    # lister les fils où je suis patient
    from models import MessageThread, Professional
    threads = MessageThread.query.filter_by(patient_user_id=current_user.id).order_by(MessageThread.created_at.desc()).all()
    return render_template("patient/messages_inbox.html", threads=threads)

# === Messagerie — fil avec un pro ===
@patient_bp.route("/messages/with/<int:pro_id>", methods=["GET","POST"])
@login_required
def messages_thread_with_pro(pro_id: int):
    _ensure_patient()
    from models import MessageThread, Message, Professional
    pro = Professional.query.get_or_404(pro_id)
    thread = MessageThread.query.filter_by(professional_id=pro.id, patient_user_id=current_user.id).first()
    if not thread:
        thread = MessageThread(professional_id=pro.id, patient_user_id=current_user.id)
        db.session.add(thread); db.session.commit()

    if request.method == "POST":
        body = (request.form.get("body") or "").strip()
        att = request.files.get("attachment")
        attachment_url = None
        if att and getattr(att, "filename", ""):
            from pathlib import Path
            from werkzeug.utils import secure_filename
            root = Path(os.getenv("UPLOAD_ROOT", Path(current_app.root_path).parent / "uploads"))
            files_dir = root / "patient_files"
            files_dir.mkdir(parents=True, exist_ok=True)
            safe = secure_filename(att.filename)
            unique = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{safe}"
            fpath = files_dir / unique
            att.save(fpath)
            attachment_url = url_for("pro_office.secure_file", filename=unique)  # on réutilise la route sécurisée du BP pro

        if body or attachment_url:
            db.session.add(Message(
                thread_id=thread.id, sender_user_id=current_user.id,
                body=body or None, attachment_url=attachment_url
            ))
            db.session.commit()
        flash("Message envoyé.", "success")
        return redirect(url_for("patient_portal.messages_thread_with_pro", pro_id=pro.id))

    msgs = Message.query.filter_by(thread_id=thread.id).order_by(Message.created_at.asc()).all()
    return render_template("patient/messages_thread.html", pro=pro, thread=thread, messages=msgs)

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
