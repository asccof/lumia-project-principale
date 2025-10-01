# pro_office.py — Contrat-fix : ajouts isolés, compatibles app.py/models.py actuels
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_, and_
from datetime import datetime

from models import (
    db, User, Professional, Appointment, Specialty,
    # objets ajoutés dans models.py (contrat-fix)
    ExerciseItem, ExerciseType, Technique,
    exercise_specialties, exercise_types, exercise_techniques,
    ExerciseAssignment, ExerciseProgress,
    PatientProfile, PatientCase, PatientFile,
    MessageThread, Message, TherapeuticJournal, JournalEntry,
)

pro_office_bp = Blueprint("pro_office", __name__, template_folder="templates")

def _current_pro_or_403():
    if current_user.is_authenticated and current_user.user_type == "professional":
        pro = Professional.query.filter_by(name=current_user.username).first()
        if pro:
            return pro
    abort(403)

# === Hub bureau virtuel (liste patients, raccourcis) ===
@pro_office_bp.route("/", methods=["GET"])
@login_required
def index():
    pro = _current_pro_or_403()
    # patients liés via PatientCase (si absents, vue vide)
    cases = PatientCase.query.filter_by(professional_id=pro.id).order_by(PatientCase.created_at.desc()).all()
    upcoming = Appointment.query.filter_by(professional_id=pro.id).order_by(Appointment.appointment_date.asc()).limit(5).all()
    return render_template("pro/office/index.html", pro=pro, cases=cases, upcoming=upcoming)

# === Exercices : liste avec filtres familles/spécialités/types/techniques/format ===
@pro_office_bp.route("/exercises", methods=["GET"])
@login_required
def exercises_index():
    pro = _current_pro_or_403()
    q = (request.args.get("q") or "").strip()
    family = (request.args.get("family") or "").strip()
    specialty_id = request.args.get("specialty_id", type=int)
    type_id = request.args.get("type_id", type=int)
    technique_id = request.args.get("technique_id", type=int)
    fmt = (request.args.get("format") or "").strip().lower()
    owner = (request.args.get("owner") or "me").strip()  # "me"|"all"
    sort = (request.args.get("sort") or "recent").strip()

    query = ExerciseItem.query.filter(ExerciseItem.deleted_at.is_(None))

    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            ExerciseItem.title.ilike(like),
            ExerciseItem.description.ilike(like),
            ExerciseItem.content_text.ilike(like),
        ))
    if family:
        query = query.filter(ExerciseItem.family.ilike(family))
    if specialty_id:
        query = (query.join(exercise_specialties, ExerciseItem.id == exercise_specialties.c.exercise_id)
                      .filter(exercise_specialties.c.specialty_id == specialty_id))
    if type_id:
        query = (query.join(exercise_types, ExerciseItem.id == exercise_types.c.exercise_id)
                      .filter(exercise_types.c.type_id == type_id))
    if technique_id:
        query = (query.join(exercise_techniques, ExerciseItem.id == exercise_techniques.c.exercise_id)
                      .filter(exercise_techniques.c.technique_id == technique_id))
    if fmt:
        query = query.filter(ExerciseItem.format == fmt)

    # Visibilité/partage
    if owner == "me":
        query = query.filter(ExerciseItem.owner_id == current_user.id)
    else:
        query = query.filter(or_(
            ExerciseItem.owner_id == current_user.id,
            ExerciseItem.visibility == "public_admin"
        ))

    # Tri
    if sort == "title":
        query = query.order_by(ExerciseItem.title.asc())
    elif sort == "popular":
        query = query.order_by(ExerciseItem.updated_at.desc(), ExerciseItem.created_at.desc())
    else:
        query = query.order_by(ExerciseItem.created_at.desc())

    rows = query.all()

    # Taxonomies pour UI
    families = [r[0] for r in db.session.query(Specialty.category).filter(
        Specialty.category.isnot(None), Specialty.category != ""
    ).distinct().order_by(Specialty.category.asc()).all()]
    specialties = Specialty.query.order_by(Specialty.name.asc()).all()
    types = ExerciseType.query.order_by(ExerciseType.name.asc()).all()
    techniques = Technique.query.order_by(Technique.name.asc()).all()

    return render_template("pro/office/exercises_index.html",
                           pro=pro, rows=rows, q=q, family=family, specialty_id=specialty_id,
                           type_id=type_id, technique_id=technique_id, fmt=fmt, owner=owner, sort=sort,
                           families=families, specialties=specialties, types=types, techniques=techniques)

# === Création / édition d’un exercice (pro & admin) ===
@pro_office_bp.route("/exercises/new", methods=["GET","POST"])
@login_required
def exercises_new():
    pro = _current_pro_or_403()
    if request.method == "POST":
        f = request.form
        item = ExerciseItem(
            title=(f.get("title") or "").strip(),
            description=(f.get("description") or "").strip(),
            format=(f.get("format") or "texte").strip().lower(),
            content_text=(f.get("content_text") or None),
            content_url=(f.get("content_url") or None),
            owner_id=current_user.id,
            family=(f.get("family") or "").strip() or None,
            visibility=(f.get("visibility") or "private").strip(),
            is_approved=False,
        )
        db.session.add(item)
        db.session.flush()

        # liaisons
        spec_ids = [int(x) for x in f.getlist("specialty_ids") if str(x).isdigit()]
        type_ids = [int(x) for x in f.getlist("type_ids") if str(x).isdigit()]
        tech_ids = [int(x) for x in f.getlist("technique_ids") if str(x).isdigit()]
        if spec_ids:
            item.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all()
        if type_ids:
            item.types = ExerciseType.query.filter(ExerciseType.id.in_(type_ids)).all()
        if tech_ids:
            item.techniques = Technique.query.filter(Technique.id.in_(tech_ids)).all()

        db.session.commit()
        flash("Exercice créé.", "success")
        return redirect(url_for("pro_office.exercises_index"))

    families = [r[0] for r in db.session.query(Specialty.category).filter(
        Specialty.category.isnot(None), Specialty.category != ""
    ).distinct().order_by(Specialty.category.asc()).all()]
    specialties = Specialty.query.order_by(Specialty.name.asc()).all()
    types = ExerciseType.query.order_by(ExerciseType.name.asc()).all()
    techniques = Technique.query.order_by(Technique.name.asc()).all()
    return render_template("pro/office/exercises_form.html",
                           pro=pro, item=None, families=families, specialties=specialties, types=types, techniques=techniques)

@pro_office_bp.route("/exercises/<int:item_id>/edit", methods=["GET","POST"])
@login_required
def exercises_edit(item_id: int):
    pro = _current_pro_or_403()
    item = ExerciseItem.query.get_or_404(item_id)
    if item.owner_id != current_user.id and not current_user.is_admin:
        abort(403)

    if request.method == "POST":
        f = request.form
        item.title = (f.get("title") or item.title).strip()
        item.description = (f.get("description") or item.description)
        item.format = (f.get("format") or item.format).strip().lower()
        item.content_text = (f.get("content_text") or item.content_text)
        item.content_url = (f.get("content_url") or item.content_url)
        item.family = (f.get("family") or item.family)
        item.visibility = (f.get("visibility") or item.visibility)

        # liaisons
        spec_ids = [int(x) for x in f.getlist("specialty_ids") if str(x).isdigit()]
        type_ids = [int(x) for x in f.getlist("type_ids") if str(x).isdigit()]
        tech_ids = [int(x) for x in f.getlist("technique_ids") if str(x).isdigit()]
        item.specialties = Specialty.query.filter(Specialty.id.in_(spec_ids)).all() if spec_ids else []
        item.types = ExerciseType.query.filter(ExerciseType.id.in_(type_ids)).all() if type_ids else []
        item.techniques = Technique.query.filter(Technique.id.in_(tech_ids)).all() if tech_ids else []

        db.session.commit()
        flash("Exercice mis à jour.", "success")
        return redirect(url_for("pro_office.exercises_index"))

    families = [r[0] for r in db.session.query(Specialty.category).filter(
        Specialty.category.isnot(None), Specialty.category != ""
    ).distinct().order_by(Specialty.category.asc()).all()]
    specialties = Specialty.query.order_by(Specialty.name.asc()).all()
    types = ExerciseType.query.order_by(ExerciseType.name.asc()).all()
    techniques = Technique.query.order_by(Technique.name.asc()).all()
    return render_template("pro/office/exercises_form.html",
                           pro=pro, item=item, families=families, specialties=specialties, types=types, techniques=techniques)
@pro_office_bp.route("/journal/<int:patient_user_id>", methods=["GET","POST"])
@login_required
def journal(patient_user_id: int):
    pro = _current_pro_or_403()
    pat = User.query.get_or_404(patient_user_id)

    journal = TherapeuticJournal.query.filter_by(professional_id=pro.id, patient_user_id=pat.id).first()
    if not journal:
        journal = TherapeuticJournal(professional_id=pro.id, patient_user_id=pat.id)
        db.session.add(journal); db.session.commit()

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        content = (request.form.get("content") or "").strip()
        checklist_json = None
        mood = request.form.get("mood", type=int)
        db.session.add(JournalEntry(
            journal_id=journal.id, author_role="pro",
            title=title or None, content=content or None,
            checklist_json=checklist_json, mood_score=mood
        ))
        db.session.commit()
        return redirect(url_for("pro_office.journal", patient_user_id=pat.id))

    entries = JournalEntry.query.filter_by(journal_id=journal.id).order_by(JournalEntry.created_at.asc()).all()
    return render_template("pro/office/journal.html", pro=pro, patient=pat, entries=entries)

# === Partage / assignation (simplifié phase 1) ===
@pro_office_bp.route("/exercises/<int:item_id>/assign", methods=["POST"])
@login_required
def exercises_assign(item_id: int):
    pro = _current_pro_or_403()
    item = ExerciseItem.query.get_or_404(item_id)
    if item.owner_id != current_user.id and not current_user.is_admin:
        abort(403)
    patient_user_id = request.form.get("patient_user_id", type=int)
    note_pro = (request.form.get("note_pro") or "").strip()
    if not patient_user_id:
        flash("Patient requis.", "warning")
        return redirect(url_for("pro_office.exercises_index"))
    assign = ExerciseAssignment(
        exercise_id=item.id, professional_id=pro.id,
        patient_user_id=patient_user_id, note_pro=note_pro
    )
    db.session.add(assign); db.session.commit()
    flash("Exercice assigné au patient.", "success")
    return redirect(url_for("pro_office.exercises_index"))
# === Messagerie — boîte du pro (liste des fils) ===
@pro_office_bp.route("/messages", methods=["GET"])
@login_required
def messages_inbox():
    pro = _current_pro_or_403()
    threads = MessageThread.query.filter_by(professional_id=pro.id).order_by(MessageThread.created_at.desc()).all()
    return render_template("pro/office/messages_inbox.html", pro=pro, threads=threads)

# === Messagerie — fil avec un patient ===
@pro_office_bp.route("/messages/<int:patient_user_id>", methods=["GET","POST"])
@login_required
def messages_thread(patient_user_id: int):
    pro = _current_pro_or_403()
    user = User.query.get_or_404(patient_user_id)

    # récupère ou crée le thread
    thread = MessageThread.query.filter_by(professional_id=pro.id, patient_user_id=user.id).first()
    if not thread:
        thread = MessageThread(professional_id=pro.id, patient_user_id=user.id)
        db.session.add(thread); db.session.commit()

    # envoi message
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
            attachment_url = url_for("pro_office.secure_file", filename=unique)

        if body or attachment_url:
            db.session.add(Message(
                thread_id=thread.id, sender_user_id=current_user.id,
                body=body or None, attachment_url=attachment_url
            ))
            db.session.commit()
        flash("Message envoyé.", "success")
        # (option) notifier le patient par email via safe_send_email ici
        return redirect(url_for("pro_office.messages_thread", patient_user_id=user.id))

    msgs = Message.query.filter_by(thread_id=thread.id).order_by(Message.created_at.asc()).all()

    # anonymat : si PatientCase.is_anonymous = True, on prépare un alias
    case = PatientCase.query.filter_by(professional_id=pro.id, patient_user_id=user.id).first()
    alias = (case.display_name or "Patient anonyme") if (case and case.is_anonymous) else (user.username or f"Patient {user.id}")

    return render_template("pro/office/messages_thread.html",
                           pro=pro, patient=user, alias=alias, thread=thread, messages=msgs)

# === Service de fichier protégé du chat (autorisation par thread) ===
@pro_office_bp.route("/files/<path:filename>")
@login_required
def secure_file(filename: str):
    from pathlib import Path
    # autoriser uniquement si current_user est pro OU patient du thread de la pièce jointe
    # (simplifié : on sert si connecté pro — pour la V1. Pour plus fin: stocker thread_id dans le nom, etc.)
    if current_user.user_type not in ("professional", "patient"):
        abort(403)
    root = Path(os.getenv("UPLOAD_ROOT", Path(current_app.root_path).parent / "uploads")) / "patient_files"
    target = root / filename
    if not target.exists():
        abort(404)
    return send_from_directory(str(root), filename, as_attachment=True, conditional=True)

# === Attacher/éditer le lien Google Meet sur une séance ===
@pro_office_bp.route("/sessions/<int:appointment_id>/meet", methods=["POST"])
@login_required
def attach_meet(appointment_id: int):
    pro = _current_pro_or_403()
    ap = Appointment.query.get_or_404(appointment_id)
    if ap.professional_id != pro.id:
        abort(403)
    meet_url = (request.form.get("meet_url") or "").strip()
    ap.meet_url = meet_url or None
    db.session.commit()
    flash("Lien Google Meet enregistré.", "success")
    return redirect(request.referrer or url_for("pro_office.index"))
