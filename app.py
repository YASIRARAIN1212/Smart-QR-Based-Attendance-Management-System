import os
import secrets
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_migrate import Migrate
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from models import db, User
from auth import login_required, get_current_user, log_audit
from mailer import mail, send_weekly_report, send_email
from captcha import generate_captcha_code, generate_captcha_image, hash_captcha_code, verify_captcha
from extensions import csrf
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
import pytz
import atexit
import requests

# Import blueprints
from views.student import student_bp
from views.teacher import teacher_bp
from views.admin import admin_bp

def create_app():
    app = Flask(__name__)
    
    # Configuration
    # Use a strong random key in production via environment variable
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        # Only allow dev key in development mode
        if os.environ.get('FLASK_ENV') == 'production':
            raise ValueError("SECRET_KEY environment variable must be set in production!")
        secret_key = 'dev-secret-key-change-in-production'
        print("WARNING: Using development SECRET_KEY. Set SECRET_KEY environment variable for production!")
    
    app.config['SECRET_KEY'] = secret_key
    
    # Database configuration - honor DATABASE_URL for production
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        # Only allow SQLite default in development mode
        if os.environ.get('FLASK_ENV') == 'production':
            raise ValueError("DATABASE_URL environment variable must be set in production!")
        db_url = 'sqlite:///attendance.db'
        print("WARNING: Using SQLite database. Set DATABASE_URL environment variable for production!")
    
    # Fix postgres:// to postgresql:// for SQLAlchemy compatibility
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Mail configuration
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    app.config['MAIL_SERVER'] = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    app.config['MAIL_PORT'] = smtp_port
    app.config['MAIL_USE_SSL'] = (smtp_port == 465)  # ✓ SSL for port 465
    app.config['MAIL_USE_TLS'] = (smtp_port == 587)  # ✓ TLS for port 587
    app.config['MAIL_USERNAME'] = os.environ.get('SMTP_USER', '')
    app.config['MAIL_PASSWORD'] = os.environ.get('SMTP_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.system')

    # Google reCAPTCHA configuration
    app.config['RECAPTCHA_SITE_KEY'] = os.environ.get('RECAPTCHA_SITE_KEY', '')
    app.config['RECAPTCHA_SECRET_KEY'] = os.environ.get('RECAPTCHA_SECRET_KEY', '')
    
    # Initialize extensions
    db.init_app(app)
    migrate = Migrate(app, db)
    csrf.init_app(app)
    mail.init_app(app)
    
    # Initialize rate limiter for DDoS protection
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"],
        storage_uri="memory://"
    )
    
    # Custom rate limit error handler
    @app.errorhandler(429)
    def ratelimit_handler(e):
        flash('Too many requests. Please slow down and try again later.', 'warning')
        return render_template('error.html', error='Rate Limit Exceeded', message='Too many requests. Please try again later.'), 429
    
    # Register blueprints
    app.register_blueprint(student_bp)
    app.register_blueprint(teacher_bp)
    app.register_blueprint(admin_bp)
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    # Setup scheduler for weekly reports
    scheduler = BackgroundScheduler()
    
    def send_weekly_reports_job():
        """Job to send weekly reports to all students"""
        with app.app_context():
            students = User.query.filter(User.role.in_(['undergraduate', 'postgraduate']), User.is_active == True).all()
            success_count = 0
            error_count = 0
            
            for student in students:
                try:
                    success, message = send_weekly_report(student.id)
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                        print(f"Error sending report to {student.email}: {message}")
                except Exception as e:
                    error_count += 1
                    print(f"Exception sending report to {student.email}: {e}")
            
            log_audit(
                action='WEEKLY_REPORTS_SCHEDULED',
                details=f'Sent to {success_count} students, {error_count} errors'
            )
            
            print(f"Weekly reports job completed: {success_count} success, {error_count} errors")
    
    # Schedule weekly reports every Monday at 07:00
    scheduler.add_job(
        func=send_weekly_reports_job,
        trigger='cron',
        day_of_week='mon',
        hour=7,
        minute=0,
        id='weekly_reports',
        name='Send weekly attendance reports',
        replace_existing=True
    )
    
    app.extensions['campus_scheduler'] = scheduler
    scheduler.start()
    
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())
    
    # Routes
    @app.route('/')
    def index():
        if 'user_id' in session:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))
    
    @app.route('/auth/admin', methods=['GET', 'POST'])
    @limiter.limit("10 per minute")
    def admin_login():
        """Dedicated admin login page"""
        # Generate or retrieve CAPTCHA
        if 'captcha_code' not in session:
            captcha_code = generate_captcha_code()
            session['captcha_text'] = captcha_code
            session['captcha_code'] = hash_captcha_code(captcha_code)
        
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            captcha_input = request.form.get('captcha')
            
            # Verify CAPTCHA
            if not verify_captcha(captcha_input, session.get('captcha_code', '')):
                flash('Invalid verification code. Please try again.', 'danger')
                captcha_code = generate_captcha_code()
                session['captcha_text'] = captcha_code
                session['captcha_code'] = hash_captcha_code(captcha_code)
                return render_template('auth/admin_login.html')
            
            user = User.query.filter_by(email=email).first()
            
            if user and user.check_password(password):
                if user.role != 'admin':
                    flash('Access denied. Admin credentials required.', 'danger')
                    captcha_code = generate_captcha_code()
                    session['captcha_text'] = captcha_code
                    session['captcha_code'] = hash_captcha_code(captcha_code)
                    log_audit(
                        action='ADMIN_LOGIN_FAILED',
                        details=f'Non-admin user {email} attempted admin login',
                        ip_address=request.remote_addr
                    )
                    return render_template('auth/admin_login.html')
                
                if not user.is_active:
                    flash('Your account is inactive. Please contact a system administrator.', 'danger')
                    captcha_code = generate_captcha_code()
                    session['captcha_text'] = captcha_code
                    session['captcha_code'] = hash_captcha_code(captcha_code)
                    return render_template('auth/admin_login.html')
                
                # Successful admin login
                session['user_id'] = user.id
                session['user_role'] = user.role
                session['user_name'] = user.full_name
                session.pop('captcha_code', None)
                session.pop('captcha_text', None)
                
                log_audit(
                    user_id=user.id,
                    action='ADMIN_LOGIN',
                    details=f'Admin {email} logged in',
                    ip_address=request.remote_addr
                )
                
                flash(f'Welcome back, {user.full_name}!', 'success')
                return redirect(url_for('admin.dashboard'))
            else:
                flash('Invalid credentials', 'danger')
                captcha_code = generate_captcha_code()
                session['captcha_code'] = hash_captcha_code(captcha_code)
                session['captcha_text'] = captcha_code
                log_audit(
                    action='ADMIN_LOGIN_FAILED',
                    details=f'Failed admin login attempt for {email}',
                    ip_address=request.remote_addr
                )
        
        return render_template('auth/admin_login.html', captcha_image=session.get('captcha_image'))
    
    @app.route('/login', methods=['GET', 'POST'])
    @app.route('/login/<role_type>', methods=['GET', 'POST'])
    @limiter.limit("10 per minute")
    def login(role_type='employee'):
        # Generate or retrieve CAPTCHA
        if 'captcha_code' not in session:
            captcha_code = generate_captcha_code()
            session['captcha_code'] = hash_captcha_code(captcha_code)
            session['captcha_text'] = captcha_code
        
        if request.method == 'POST':
            email = request.form.get('email')
            password = request.form.get('password')
            captcha_input = request.form.get('captcha')
            selected_role = request.form.get('role_type', role_type)
            
            # Verify CAPTCHA
            if not verify_captcha(captcha_input, session.get('captcha_code', '')):
                flash('Invalid verification code. Please try again.', 'danger')
                # Generate new CAPTCHA
                captcha_code = generate_captcha_code()
                session['captcha_code'] = hash_captcha_code(captcha_code)
                session['captcha_text'] = captcha_code
                
                log_audit(
                    action='LOGIN_FAILED_CAPTCHA',
                    details=f'Failed CAPTCHA for {email}',
                    ip_address=request.remote_addr
                )
                return render_template('auth/login.html', role_type=selected_role, )
            
            user = User.query.filter_by(email=email).first()
            
            # Role-based validation
            if user and user.check_password(password):
                if not user.is_active:
                    flash('Your account is inactive. Please contact an administrator.', 'danger')
                    # Regenerate CAPTCHA
                    captcha_code = generate_captcha_code()
                    session['captcha_code'] = hash_captcha_code(captcha_code)
                    session['captcha_text'] = captcha_code
                    return redirect(url_for('login', role_type=selected_role))
                
                # Check role matches selected portal
                if selected_role == 'admin':
                    if user.role != 'admin':
                        flash('Invalid credentials for admin portal', 'danger')
                        captcha_code = generate_captcha_code()
                        session['captcha_code'] = hash_captcha_code(captcha_code)
                        session['captcha_text'] = captcha_code
                        log_audit(
                            action='LOGIN_FAILED',
                            details=f'Wrong portal access attempt: {email} tried admin portal with role {user.role}',
                            ip_address=request.remote_addr
                        )
                        return redirect(url_for('login', role_type=selected_role))
                elif user.role != selected_role:
                    flash('Invalid username or password', 'danger')
                    captcha_code = generate_captcha_code()
                    session['captcha_code'] = hash_captcha_code(captcha_code)
                    session['captcha_text'] = captcha_code
                    log_audit(
                        action='LOGIN_FAILED',
                        details=f'Wrong portal access: {email} tried {selected_role} portal with role {user.role}',
                        ip_address=request.remote_addr
                    )
                    return redirect(url_for('login', role_type=selected_role))
                
                # Successful login
                session['user_id'] = user.id
                session['user_role'] = user.role
                session['user_name'] = user.full_name
                session.pop('captcha_code', None)
                session.pop('captcha_text', None)
                
                log_audit(
                    user_id=user.id,
                    action='LOGIN',
                    details=f'User {email} logged in via {selected_role} portal',
                    ip_address=request.remote_addr
                )
                
                # Check if password reset required
                if user.force_password_reset:
                    flash('You must change your password before continuing.', 'warning')
                    return redirect(url_for('change_password_first_login'))
                
                flash(f'Welcome back, {user.full_name}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password', 'danger')
                # Regenerate CAPTCHA after failed attempt
                captcha_code = generate_captcha_code()
                session['captcha_code'] = hash_captcha_code(captcha_code)
                session['captcha_text'] = captcha_code
                
                log_audit(
                    action='LOGIN_FAILED',
                    details=f'Failed login attempt for {email} on {selected_role} portal',
                    ip_address=request.remote_addr
                )
        
        return render_template('auth/login.html', role_type=role_type, captcha_image=session.get('captcha_image'))
    
    @app.route('/change-password-required', methods=['GET', 'POST'])
    @login_required
    def change_password_first_login():
        """Force password change for new users"""
        user = get_current_user()
        
        if not user:
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('login'))
        
        if not user.force_password_reset:
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            if not new_password or len(new_password) < 8:
                flash('Password must be at least 8 characters long', 'danger')
            elif new_password != confirm_password:
                flash('Passwords do not match', 'danger')
            else:
                user.set_password(new_password)
                user.force_password_reset = False
                user.last_password_change_at = datetime.now(pytz.UTC)
                db.session.commit()
                
                log_audit(
                    user_id=user.id,
                    action='PASSWORD_CHANGED',
                    details='First-time password change completed',
                    ip_address=request.remote_addr
                )
                
                flash('Password changed successfully!', 'success')
                return redirect(url_for('dashboard'))
        
        return render_template('auth/change_password_required.html', user=user)
    
    @app.route('/dashboard')
    @login_required
    def dashboard():
        user = get_current_user()
        
        if not user:
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('login'))
        
        if user.role in ['undergraduate', 'postgraduate']:
            return redirect(url_for('student.dashboard'))
        elif user.role == 'employee':
            return redirect(url_for('teacher.dashboard'))
        elif user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            flash('Invalid user role', 'danger')
            return redirect(url_for('logout'))
    
    @app.route('/logout')
    def logout():
        user_id = session.get('user_id')
        if user_id:
            log_audit(
                user_id=user_id,
                action='LOGOUT',
                details='User logged out',
                ip_address=request.remote_addr
            )
        
        session.clear()
        flash('You have been logged out', 'info')
        return redirect(url_for('login'))
    
    @app.route('/captcha.png')
    def serve_captcha():
        """Serve CAPTCHA image"""
        if 'captcha_text' not in session:
            captcha_code = generate_captcha_code()
            session['captcha_text'] = captcha_code
            session['captcha_code'] = hash_captcha_code(captcha_code)
        
        captcha_image = generate_captcha_image(session['captcha_text'])
        from flask import Response
        return Response(captcha_image, mimetype='image/png')
    
    @app.route('/refresh_captcha', methods=['GET'])
    def refresh_captcha():
        """Refresh CAPTCHA code"""
        import time
        captcha_code = generate_captcha_code()
        session['captcha_text'] = captcha_code
        session['captcha_code'] = hash_captcha_code(captcha_code)
        return jsonify({'success': True, 'timestamp': time.time()})
    
    # Password Reset Routes
    @app.route('/forgot-password', methods=['GET', 'POST'])
    @limiter.limit("5 per hour")
    def forgot_password():
        if request.method == 'POST':
            # Verify CAPTCHA if configured
            recaptcha_response = request.form.get('g-recaptcha-response')
            if app.config.get('RECAPTCHA_SECRET_KEY'):
                if not verify_recaptcha(recaptcha_response):
                    flash('Please complete the CAPTCHA verification.', 'danger')
                    return render_template('auth/forgot_password.html', recaptcha_site_key=app.config.get('RECAPTCHA_SITE_KEY'))
            
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()
            
            if user:
                # Generate reset token
                reset_token = secrets.token_urlsafe(32)
                user.reset_token = reset_token
                user.reset_token_expiry = datetime.now(pytz.UTC) + timedelta(hours=1)
                db.session.commit()
                
                # Send reset email
                reset_url = url_for('reset_password', token=reset_token, _external=True)
                html_body = render_template('email/password_reset.html', 
                                           user=user, 
                                           reset_url=reset_url)
                text_body = f"Reset your password by clicking this link: {reset_url}\n\nThis link expires in 1 hour."
                
                success, message = send_email(
                    subject="Password Reset Request - Smart Attendance System",
                    recipients=user.email,
                    html_body=html_body,
                    text_body=text_body
                )
                
                log_audit(
                    user_id=user.id,
                    action='PASSWORD_RESET_REQUESTED',
                    details=f'Password reset email sent to {email}',
                    ip_address=request.remote_addr
                )
            
            # Always show success message to prevent email enumeration
            flash('If an account with that email exists, a password reset link has been sent.', 'info')
            return redirect(url_for('login'))
        
        return render_template('auth/forgot_password.html', recaptcha_site_key=app.config.get('RECAPTCHA_SITE_KEY'))
    
    @app.route('/reset-password/<token>', methods=['GET', 'POST'])
    @limiter.limit("10 per hour")
    def reset_password(token):
        user = User.query.filter_by(reset_token=token).first()
        
        if not user or not user.reset_token_expiry:
            flash('Invalid or expired reset link. Please request a new one.', 'danger')
            return redirect(url_for('forgot_password'))
        
        expiry_time = user.reset_token_expiry
        if expiry_time.tzinfo is None:
            expiry_time = pytz.UTC.localize(expiry_time)
        
        if expiry_time < datetime.now(pytz.UTC):
            flash('Invalid or expired reset link. Please request a new one.', 'danger')
            return redirect(url_for('forgot_password'))
        
        if request.method == 'POST':
            new_password = request.form.get('password')
            confirm_password = request.form.get('confirm_password')
            
            if not new_password or len(new_password) < 8:
                flash('Password must be at least 8 characters long.', 'danger')
                return render_template('auth/reset_password.html', token=token)
            
            if new_password != confirm_password:
                flash('Passwords do not match.', 'danger')
                return render_template('auth/reset_password.html', token=token)
            
            # Update password
            user.set_password(new_password)
            user.reset_token = None
            user.reset_token_expiry = None
            db.session.commit()
            
            log_audit(
                user_id=user.id,
                action='PASSWORD_RESET_COMPLETED',
                details=f'Password successfully reset for {user.email}',
                ip_address=request.remote_addr
            )
            
            flash('Your password has been reset successfully. Please log in with your new password.', 'success')
            return redirect(url_for('login'))
        
        return render_template('auth/reset_password.html', token=token)
    
    # Helper function for CAPTCHA verification
    def verify_recaptcha(recaptcha_response):
        """Verify Google reCAPTCHA response"""
        secret_key = app.config.get('RECAPTCHA_SECRET_KEY')
        
        if not secret_key:
            return True
        
        try:
            response = requests.post('https://www.google.com/recaptcha/api/siteverify', data={
                'secret': secret_key,
                'response': recaptcha_response,
                'remoteip': request.remote_addr
            })
            result = response.json()
            return result.get('success', False)
        except Exception as e:
            print(f"CAPTCHA verification error: {e}")
            return False
    
    return app

if __name__ == '__main__':
    app = create_app()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)