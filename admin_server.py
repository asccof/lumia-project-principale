from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'admin_cle_secrete_ici'
app.config['SESSION_COOKIE_NAME'] = 'tighri_admin_session'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tighri.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'admin_login'

# Modèles de base de données (même que l'app principale)
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(20), default='patient')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

class Professional(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    consultation_fee = db.Column(db.Float, nullable=False)
    image_url = db.Column(db.String(200))
    specialty = db.Column(db.String(50), nullable=False)
    availability = db.Column(db.String(100), default='disponible')
    consultation_types = db.Column(db.String(100), default='cabinet')
    location = db.Column(db.String(100), default='Casablanca')
    phone = db.Column(db.String(20), default='+212 6 XX XX XX XX')
    experience_years = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='en_attente')  # en_attente, valide, rejete
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    professional_id = db.Column(db.Integer, db.ForeignKey('professional.id'), nullable=False)
    appointment_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default='en_attente')
    consultation_type = db.Column(db.String(20), default='cabinet')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    patient = db.relationship('User', foreign_keys=[patient_id], backref='appointments_as_patient')
    professional = db.relationship('Professional', foreign_keys=[professional_id], backref='appointments')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Routes d'authentification admin
@app.route('/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password) and user.is_admin:
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Identifiants incorrects ou accès non autorisé')
    
    return render_template('admin_login.html')

@app.route('/logout')
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('admin_login'))

# Route principale admin
@app.route('/')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professionals = Professional.query.all()
    users = User.query.all()
    appointments = Appointment.query.all()
    
    # Statistiques
    total_professionals = len(professionals)
    total_users = len(users)
    total_appointments = len(appointments)
    total_revenue = sum(appointment.professional.consultation_fee for appointment in appointments if appointment.status == 'confirme' and appointment.professional)
    
    return render_template('admin_dashboard.html', 
                         professionals=professionals, 
                         users=users, 
                         appointments=appointments,
                         total_professionals=total_professionals,
                         total_users=total_users,
                         total_appointments=total_appointments,
                         total_revenue=total_revenue)

# Gestion des professionnels
@app.route('/products')
@login_required
def admin_products():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professionals = Professional.query.all()
    return render_template('admin_products.html', professionals=professionals)

@app.route('/products/add', methods=['GET', 'POST'])
@login_required
def admin_add_product():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        consultation_fee = float(request.form['consultation_fee'])
        specialty = request.form['specialty']
        location = request.form['location']
        experience_years = int(request.form['experience_years'])
        image_url = request.form.get('image_url', '')
        phone = request.form.get('phone', '+212 6 XX XX XX XX')
        email = request.form.get('email', '')
        
        professional = Professional(
            name=name, 
            description=description, 
            consultation_fee=consultation_fee, 
            specialty=specialty, 
            location=location,
            experience_years=experience_years,
            image_url=image_url,
            phone=phone
        )
        db.session.add(professional)
        db.session.commit()
        
        flash('Professionnel ajouté avec succès!')
        return redirect(url_for('admin_products'))
    
    return render_template('add_product.html')

@app.route('/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_product(product_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professional = Professional.query.get_or_404(product_id)
    
    if request.method == 'POST':
        professional.name = request.form['name']
        professional.description = request.form['description']
        professional.consultation_fee = float(request.form['consultation_fee'])
        professional.specialty = request.form['specialty']
        professional.status = request.form['status']
        professional.image_url = request.form.get('image_url', '')
        
        db.session.commit()
        flash('Professionnel modifié avec succès!')
        return redirect(url_for('admin_products'))
    
    return render_template('edit_product.html', professional=professional)

@app.route('/products/<int:product_id>/delete', methods=['POST'])
@login_required
def admin_delete_product(product_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    
    professional = Professional.query.get_or_404(product_id)
    db.session.delete(professional)
    db.session.commit()
    
    return jsonify({'success': True, 'message': 'Professionnel supprimé avec succès'})

@app.route('/professionals')
@login_required
def admin_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professionals = Professional.query.all()
    return render_template('admin_professionals.html', professionals=professionals)

@app.route('/professionals/add', methods=['GET', 'POST'])
@login_required
def add_professional():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        consultation_fee = float(request.form['consultation_fee'])
        specialty = request.form['specialty']
        location = request.form['location']
        experience_years = int(request.form['experience_years'])
        image_url = request.form['image_url']
        
        professional = Professional(
            name=name, 
            description=description, 
            consultation_fee=consultation_fee, 
            specialty=specialty, 
            location=location,
            experience_years=experience_years,
            image_url=image_url
        )
        db.session.add(professional)
        db.session.commit()
        
        flash('Professionnel ajouté avec succès!')
        return redirect(url_for('admin_professionals'))
    
    return render_template('add_professional.html')

@app.route('/professionals/edit/<int:professional_id>', methods=['GET', 'POST'])
@login_required
def edit_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professional = Professional.query.get_or_404(professional_id)
    
    if request.method == 'POST':
        professional.name = request.form['name']
        professional.description = request.form['description']
        professional.consultation_fee = float(request.form['consultation_fee'])
        professional.specialty = request.form['specialty']
        professional.location = request.form['location']
        professional.experience_years = int(request.form['experience_years'])
        professional.image_url = request.form['image_url']
        
        db.session.commit()
        flash('Professionnel modifié avec succès!')
        return redirect(url_for('admin_professionals'))
    
    return render_template('edit_professional.html', professional=professional)

@app.route('/professionals/delete/<int:professional_id>')
@login_required
def delete_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professional = Professional.query.get_or_404(professional_id)
    db.session.delete(professional)
    db.session.commit()
    flash('Professionnel supprimé avec succès!')
    return redirect(url_for('admin_professionals'))

@app.route('/professionals/<int:professional_id>')
@login_required
def view_professional(professional_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    professional = Professional.query.get_or_404(professional_id)
    # Récupérer les rendez-vous de ce professionnel
    appointments = Appointment.query.filter_by(professional_id=professional_id).all()
    
    return render_template('view_professional.html', professional=professional, appointments=appointments)

# Gestion des utilisateurs
@app.route('/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    users = User.query.all()
    return render_template('admin_users.html', users=users)

@app.route('/users/add', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']
        is_admin = 'is_admin' in request.form
        
        # Vérifier si l'utilisateur existe déjà
        if User.query.filter_by(username=username).first():
            flash('Nom d\'utilisateur déjà utilisé')
            return redirect(url_for('add_user'))
        
        if User.query.filter_by(email=email).first():
            flash('Email déjà utilisé')
            return redirect(url_for('add_user'))
        
        user = User(
            username=username, 
            email=email, 
            password_hash=generate_password_hash(password),
            user_type=user_type,
            is_admin=is_admin
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Utilisateur ajouté avec succès!')
        return redirect(url_for('admin_users'))
    
    return render_template('add_user.html')

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.username = request.form['username']
        user.email = request.form['email']
        user.user_type = request.form['user_type']
        user.is_admin = 'is_admin' in request.form
        
        if request.form['password']:
            user.password_hash = generate_password_hash(request.form['password'])
        
        db.session.commit()
        flash('Utilisateur modifié avec succès!')
        return redirect(url_for('admin_users'))
    
    return render_template('edit_user.html', user=user)

@app.route('/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('Utilisateur supprimé avec succès!')
    return redirect(url_for('admin_users'))

# Gestion des rendez-vous
@app.route('/orders')
@login_required
def admin_orders():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    appointments = Appointment.query.all()
    return render_template('admin_orders.html', appointments=appointments)

@app.route('/appointments')
@login_required
def admin_appointments():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    appointments = Appointment.query.all()
    return render_template('admin_appointments.html', appointments=appointments)

@app.route('/orders/<int:appointment_id>/status', methods=['POST'])
@login_required
def update_appointment_status(appointment_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    
    try:
        data = request.get_json()
        new_status = data.get('status')
        
        if new_status not in ['confirme', 'en_attente', 'annule']:
            return jsonify({'success': False, 'message': 'Statut invalide'}), 400
        
        appointment = Appointment.query.get_or_404(appointment_id)
        appointment.status = new_status
        db.session.commit()
        
        return jsonify({'success': True, 'message': f'Rendez-vous {new_status}'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

# API pour les statistiques
@app.route('/api/stats')
@login_required
def api_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Accès refusé'}), 403
    
    professionals = Professional.query.all()
    users = User.query.all()
    appointments = Appointment.query.all()
    
    stats = {
        'total_professionals': len(professionals),
        'total_users': len(users),
        'total_appointments': len(appointments),
        'confirmed_appointments': len([a for a in appointments if a.status == 'confirme']),
        'pending_appointments': len([a for a in appointments if a.status == 'en_attente'])
    }
    
    return jsonify(stats)

@app.route('/professionals/<int:professional_id>/validate', methods=['POST'])
@login_required
def validate_professional(professional_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    
    try:
        professional = Professional.query.get_or_404(professional_id)
        professional.status = 'valide'
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Professionnel validé avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/professionals/<int:professional_id>/reject', methods=['POST'])
@login_required
def reject_professional(professional_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': 'Accès refusé'}), 403
    
    try:
        professional = Professional.query.get_or_404(professional_id)
        professional.status = 'rejete'
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Professionnel rejeté'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/pending-professionals')
@login_required
def pending_professionals():
    if not current_user.is_admin:
        flash('Accès refusé')
        return redirect(url_for('admin_login'))
    
    pending_professionals = Professional.query.filter_by(status='en_attente').all()
    return render_template('pending_professionals.html', professionals=pending_professionals)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Créer un admin par défaut si aucun utilisateur n'existe
        if not User.query.first():
            admin = User(
                username='admin',
                email='admin@tighri.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                user_type='professional'
            )
            db.session.add(admin)
            db.session.commit()
    
    # Configuration du statut du serveur admin
    app.config['ADMIN_STATUS'] = {
        'server_started': True,
        'admin_credentials': 'admin / admin123',
        'database_ready': True,
        'startup_time': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    }
    
    app.run(debug=True, port=8080) 