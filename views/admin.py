from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, current_app
from auth import login_required, role_required, get_current_user, log_audit
from models import db, User, Subject, Session, Attendance, AuditLog, FamilyEmail, Enrollment
from mailer import send_weekly_report, send_test_email
from datetime import datetime
import pytz

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.route('/dashboard')
@role_required('admin')
def dashboard():
    """Admin dashboard"""
    user = get_current_user()
    assert user is not None

    # Get statistics
    total_users = User.query.count()
    total_students = User.query.filter(
        User.role.in_(['undergraduate', 'postgraduate'])).count()
    total_employees = User.query.filter_by(role='employee').count()
    total_admins = User.query.filter_by(role='admin').count()
    total_subjects = Subject.query.filter_by(is_active=True).count()
    total_sessions = Session.query.filter_by(is_active=True).count()
    total_attendance = Attendance.query.filter_by(
        verification_status='VERIFIED').count()

    # Recent audit logs
    recent_logs = AuditLog.query.order_by(
        AuditLog.timestamp.desc()).limit(20).all()

    return render_template('admin/dashboard.html',
                           user=user,
                           total_users=total_users,
                           total_students=total_students,
                           total_teachers=total_employees,
                           total_employees=total_employees,
                           total_admins=total_admins,
                           total_subjects=total_subjects,
                           total_sessions=total_sessions,
                           total_attendance=total_attendance,
                           recent_logs=recent_logs)


@admin_bp.route('/users')
@role_required('admin')
def list_users():
    """List all users with filtering and sorting"""
    user = get_current_user()
    assert user is not None

    # Get filter parameters
    role_filter = request.args.get('role', 'all')
    department_filter = request.args.get('department', 'all')
    year_filter = request.args.get('year', 'all')
    sort_by = request.args.get('sort', 'created_at')

    # Base query
    query = User.query

    # Apply filters
    if role_filter != 'all':
        query = query.filter_by(role=role_filter)
    if department_filter != 'all':
        query = query.filter_by(department=department_filter)
    if year_filter != 'all':
        query = query.filter_by(year=int(year_filter))

    # Apply sorting
    if sort_by == 'name':
        query = query.order_by(User.full_name)
    elif sort_by == 'email':
        query = query.order_by(User.email)
    elif sort_by == 'department':
        query = query.order_by(User.department.desc())
    elif sort_by == 'year':
        query = query.order_by(User.year.desc())
    else:
        query = query.order_by(User.created_at.desc())

    users = query.all()

    # Get unique departments and years for filters
    departments = db.session.query(User.department).distinct().filter(
        User.department.isnot(None)).all()
    departments = [d[0] for d in departments]
    years = db.session.query(User.year).distinct().filter(
        User.year.isnot(None)).all()
    years = sorted([y[0] for y in years if y[0]])

    return render_template('admin/list_users.html',
                           user=user,
                           users=users,
                           departments=departments,
                           years=years,
                           current_role=role_filter,
                           current_dept=department_filter,
                           current_year=year_filter,
                           current_sort=sort_by)


@admin_bp.route('/users/<int:user_id>')
@role_required('admin')
def view_user(user_id):
    """View user details"""
    admin_user = get_current_user()
    assert admin_user is not None
    target_user = User.query.get_or_404(user_id)

    # Get family emails if student
    family_emails = []
    if target_user.is_student():
        family_emails = FamilyEmail.query.filter_by(student_id=user_id).all()

    # Get attendance summary if student
    attendance_summary = None
    if target_user.is_student():
        from utils import get_weekly_attendance_summary
        attendance_summary = get_weekly_attendance_summary(user_id)

    return render_template('admin/view_user.html',
                           user=admin_user,
                           target_user=target_user,
                           family_emails=family_emails,
                           attendance_summary=attendance_summary)


@admin_bp.route('/users/<int:user_id>/family_emails/add', methods=['POST'])
@role_required('admin')
def add_family_email(user_id):
    """Add family email"""
    admin_user = get_current_user()
    assert admin_user is not None
    target_user = User.query.get_or_404(user_id)

    if not target_user.is_student():
        flash('Can only add family emails for students', 'danger')
        return redirect(url_for('admin.view_user', user_id=user_id))

    try:
        email = request.form.get('email')
        relationship = request.form.get('relationship')

        if not email:
            flash('Email is required', 'danger')
            return redirect(url_for('admin.view_user', user_id=user_id))

        family_email = FamilyEmail(student_id=user_id,  # type: ignore
                                   email=email,
                                   relationship=relationship)

        db.session.add(family_email)
        db.session.commit()

        log_audit(user_id=admin_user.id,
                  action='FAMILY_EMAIL_ADDED',
                  entity_type='User',
                  entity_id=user_id,
                  details=f'Added family email: {email}',
                  ip_address=request.remote_addr)

        flash(f'Family email added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding family email: {str(e)}', 'danger')

    return redirect(url_for('admin.view_user', user_id=user_id))


@admin_bp.route('/users/<int:user_id>/family_emails/<int:email_id>/delete',
                methods=['POST'])
@role_required('admin')
def delete_family_email(user_id, email_id):
    """Delete family email"""
    admin_user = get_current_user()
    assert admin_user is not None
    family_email = FamilyEmail.query.get_or_404(email_id)

    if family_email.student_id != user_id:
        flash('Invalid family email', 'danger')
        return redirect(url_for('admin.view_user', user_id=user_id))

    try:
        email_address = family_email.email
        db.session.delete(family_email)
        db.session.commit()

        log_audit(user_id=admin_user.id,
                  action='FAMILY_EMAIL_DELETED',
                  entity_type='User',
                  entity_id=user_id,
                  details=f'Deleted family email: {email_address}',
                  ip_address=request.remote_addr)

        flash('Family email deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting family email: {str(e)}', 'danger')

    return redirect(url_for('admin.view_user', user_id=user_id))



@admin_bp.route('/scheduled-jobs')
@role_required('admin')
def scheduled_jobs():
    """Display scheduled jobs with readable schedule information."""

    scheduler = current_app.extensions.get('campus_scheduler')
    jobs = []

    if scheduler is not None:
        for job in scheduler.get_jobs():

            # Convert technical schedule into readable text
            if job.id == 'weekly_reports':
                schedule_text = 'Every Monday at 07:00 AM'
            else:
                schedule_text = str(job.trigger)

            # Format next execution in Pakistan time
            next_run = 'Not scheduled'

            if job.next_run_time:
                pakistan_tz = pytz.timezone('Asia/Karachi')
                next_run = job.next_run_time.astimezone(
                    pakistan_tz
                ).strftime('%d %B %Y, %I:%M %p PKT')

            jobs.append({
                'name': job.name,
                'id': job.id,
                'next_run': next_run,
                'trigger': schedule_text,
                'schedule': schedule_text
            })

    return render_template(
        'admin/scheduled_jobs.html',
        user=get_current_user(),
        jobs=jobs,
        running=bool(scheduler and scheduler.running)
    )



@admin_bp.route('/email-settings', methods=['GET', 'POST'])
@role_required('admin')
def email_settings():
    """Show SMTP configuration and allow a real test message.

    Passwords are only read from server environment, never displayed or saved
    through an admin form.
    """
    if request.method == 'POST':
        recipient = (request.form.get('test_email') or '').strip()
        if not recipient or '@' not in recipient or len(recipient) > 254:
            flash('Enter a valid recipient email address.', 'danger')
        elif not current_app.config.get('MAIL_USERNAME') or not current_app.config.get('MAIL_PASSWORD'):
            flash('SMTP is not configured. Set SMTP_USER and SMTP_PASSWORD in your environment.', 'warning')
        else:
            success, message = send_test_email(recipient)
            flash(message if success else 'Test email failed: ' + message,
                  'success' if success else 'danger')
            log_audit(user_id=get_current_user().id, action='SMTP_TEST',
                      details=f'Test to {recipient}: {"success" if success else "failed"}',
                      ip_address=request.remote_addr)
        return redirect(url_for('admin.email_settings'))
    cfg = current_app.config
    return render_template('admin/email_settings.html', user=get_current_user(),
                           smtp_host=cfg.get('MAIL_SERVER'), smtp_port=cfg.get('MAIL_PORT'),
                           sender=cfg.get('MAIL_DEFAULT_SENDER'),
                           smtp_user=cfg.get('MAIL_USERNAME'),
                           configured=bool(cfg.get('MAIL_USERNAME') and cfg.get('MAIL_PASSWORD')))


@admin_bp.route('/jobs/trigger', methods=['POST'])
@role_required('admin')
def trigger_job():
    """Manually trigger scheduled jobs"""
    admin_user = get_current_user()
    assert admin_user is not None
    job_type = request.form.get('job_type')

    try:
        if job_type == 'weekly_reports':
            # Send weekly reports to all students
            students = User.query.filter(
                User.role.in_(['undergraduate', 'postgraduate']),
                User.is_active == True).all()
            success_count = 0
            error_count = 0

            for student in students:
                success, message = send_weekly_report(student.id)
                if success:
                    success_count += 1
                else:
                    error_count += 1

            log_audit(
                user_id=admin_user.id,
                action='WEEKLY_REPORTS_TRIGGERED',
                details=
                f'Sent to {success_count} students, {error_count} errors',
                ip_address=request.remote_addr)

            flash(
                f'Weekly reports sent to {success_count} students ({error_count} errors)',
                'success')

        elif job_type == 'test_email':
            test_recipient = request.form.get('test_email')
            if not test_recipient:
                flash('Please provide a test email address', 'warning')
                return redirect(url_for('admin.email_settings'))

            success, message = send_test_email(test_recipient)
            if success:
                flash(f'Test email sent to {test_recipient}', 'success')
            else:
                flash(f'Error sending test email: {message}', 'danger')

            log_audit(user_id=admin_user.id,
                      action='TEST_EMAIL_SENT',
                      details=f'Test email to {test_recipient}: {message}',
                      ip_address=request.remote_addr)

        else:
            flash('Invalid job type', 'danger')

    except Exception as e:
        flash(f'Error triggering job: {str(e)}', 'danger')

    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/audit_logs')
@role_required('admin')
def audit_logs():
    """View audit logs"""
    user = get_current_user()
    assert user is not None

    page = request.args.get('page', 1, type=int)
    per_page = 50

    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False)

    return render_template('admin/audit_logs.html', user=user, logs=logs)


@admin_bp.route('/audit_logs/clear', methods=['POST'])
@role_required('admin')
def clear_audit_logs():
    """Clear all audit logs after admin password verification"""
    admin_user = get_current_user()
    assert admin_user is not None

    # Get and verify admin password
    admin_password = request.form.get('admin_password')

    if not admin_password:
        flash('Admin password is required to clear audit logs.', 'danger')
        return redirect(url_for('admin.audit_logs'))

    # Verify admin password
    if not admin_user.check_password(admin_password):
        flash('Incorrect admin password. Audit logs were not cleared.',
              'danger')
        log_audit(
            user_id=admin_user.id,
            action='AUDIT_LOG_CLEAR_FAILED',
            details='Failed attempt to clear audit logs - incorrect password',
            ip_address=request.remote_addr)
        return redirect(url_for('admin.audit_logs'))

    try:
        # Count logs before deletion
        log_count = AuditLog.query.count()

        # Delete all audit logs
        AuditLog.query.delete()
        db.session.commit()

        # Log this action (new audit log after clearing)
        log_audit(
            user_id=admin_user.id,
            action='AUDIT_LOG_CLEARED',
            details=
            f'Admin {admin_user.email} cleared {log_count} audit log entries',
            ip_address=request.remote_addr)

        flash(f'Successfully cleared {log_count} audit log entries.',
              'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error clearing audit logs: {str(e)}', 'danger')
        log_audit(user_id=admin_user.id,
                  action='AUDIT_LOG_CLEAR_ERROR',
                  details=f'Error clearing audit logs: {str(e)}',
                  ip_address=request.remote_addr)

    return redirect(url_for('admin.audit_logs'))


@admin_bp.route('/users/create', methods=['GET', 'POST'])
@role_required('admin')
def create_user():
    """Create a new user"""
    admin_user = get_current_user()
    assert admin_user is not None

    if request.method == 'POST':
        try:
            email = request.form.get('email')
            full_name = request.form.get('full_name')
            role = request.form.get('role')
            password = request.form.get('password')
            student_id = request.form.get('student_id')
            department = request.form.get('department')
            year = request.form.get('year')
            phone = request.form.get('phone')

            # Validation
            if not all([email, full_name, role, password]):
                flash('Email, full name, role, and password are required',
                      'danger')
                return redirect(url_for('admin.create_user'))

            # Check if email already exists
            if User.query.filter_by(email=email).first():
                flash('Email already exists', 'danger')
                return redirect(url_for('admin.create_user'))

            # Create user
            new_user = User(email=email,  # type: ignore
                            full_name=full_name,
                            role=role,
                            student_id=student_id if student_id else None,
                            department=department if department else None,
                            year=int(year) if year else None,
                            phone=phone if phone else None,
                            created_by_admin_id=admin_user.id,
                            force_password_reset=True,
                            is_active=True)
            new_user.set_password(password)

            db.session.add(new_user)
            db.session.commit()

            log_audit(user_id=admin_user.id,
                      action='USER_CREATED',
                      entity_type='User',
                      entity_id=new_user.id,
                      details=f'Created user: {email} with role {role}',
                      ip_address=request.remote_addr)

            flash(
                f'User {full_name} created successfully! They must change password on first login.',
                'success')
            return redirect(url_for('admin.list_users'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')

    return render_template('admin/create_user.html', user=admin_user)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def edit_user(user_id):
    """Edit user details"""
    admin_user = get_current_user()
    assert admin_user is not None
    target_user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        try:
            target_user.full_name = request.form.get('full_name')
            target_user.email = request.form.get('email')
            target_user.role = request.form.get('role')
            target_user.student_id = request.form.get('student_id') or None
            target_user.department = request.form.get('department') or None
            year_str = request.form.get('year')
            target_user.year = int(year_str) if year_str else None
            target_user.phone = request.form.get('phone') or None
            target_user.is_active = request.form.get('is_active') == 'true'

            # Check if password reset is requested
            if request.form.get('reset_password'):
                new_password = request.form.get('new_password')
                if new_password:
                    target_user.set_password(new_password)
                    target_user.force_password_reset = True
                    target_user.last_password_change_at = datetime.now(
                        pytz.UTC)

            db.session.commit()

            log_audit(user_id=admin_user.id,
                      action='USER_UPDATED',
                      entity_type='User',
                      entity_id=target_user.id,
                      details=f'Updated user: {target_user.email}',
                      ip_address=request.remote_addr)

            flash(f'User {target_user.full_name} updated successfully!',
                  'success')
            return redirect(url_for('admin.view_user', user_id=user_id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating user: {str(e)}', 'danger')

    return render_template('admin/edit_user.html',
                           user=admin_user,
                           target_user=target_user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def delete_user(user_id):
    """Delete a user"""
    admin_user = get_current_user()
    assert admin_user is not None
    target_user = User.query.get_or_404(user_id)

    # Prevent self-deletion
    if target_user.id == admin_user.id:
        flash('Cannot delete your own account', 'danger')
        return redirect(url_for('admin.list_users'))

    # Get admin password for confirmation
    admin_password = request.form.get('admin_password')
    if not admin_password or not admin_user.check_password(admin_password):
        flash('Invalid admin password', 'danger')
        return redirect(url_for('admin.view_user', user_id=user_id))

    try:
        user_email = target_user.email
        db.session.delete(target_user)
        db.session.commit()

        log_audit(user_id=admin_user.id,
                  action='USER_DELETED',
                  details=f'Deleted user: {user_email}',
                  ip_address=request.remote_addr)

        flash(f'User {user_email} deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')

    return redirect(url_for('admin.list_users'))


@admin_bp.route('/subjects/create', methods=['GET', 'POST'])
@role_required('admin')
def create_subject():
    """Admin creates a new subject for teachers"""
    admin_user = get_current_user()
    assert admin_user is not None

    if request.method == 'POST':
        try:
            name = request.form.get('name')
            code = request.form.get('code')
            description = request.form.get('description')
            teacher_id = request.form.get('teacher_id')

            if not all([name, code, teacher_id]):
                flash('Subject name, code, and teacher are required', 'danger')
                return redirect(url_for('admin.create_subject'))

            # Check if code already exists
            if Subject.query.filter_by(code=code).first():
                flash('Subject code already exists', 'danger')
                return redirect(url_for('admin.create_subject'))

            subject = Subject(name=name,  # type: ignore
                              code=code,
                              description=description,
                              teacher_id=teacher_id)

            db.session.add(subject)
            db.session.commit()

            log_audit(user_id=admin_user.id,
                      action='SUBJECT_CREATED',
                      entity_type='Subject',
                      entity_id=subject.id,
                      details=f'Admin created subject: {code} - {name}',
                      ip_address=request.remote_addr)

            flash(f'Subject "{name}" created successfully!', 'success')
            return redirect(url_for('admin.dashboard'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating subject: {str(e)}', 'danger')

    # Get all teachers/employees
    teachers = User.query.filter_by(role='employee', is_active=True).all()
    return render_template('admin/create_subject.html',
                           user=admin_user,
                           teachers=teachers)


@admin_bp.route('/sessions/create', methods=['GET', 'POST'])
@role_required('admin')
def create_session():
    """Admin creates a new session for teachers"""
    admin_user = get_current_user()
    assert admin_user is not None

    if request.method == 'POST':
        try:
            from utils import generate_qr_token, save_qr_code
            import os

            subject_id = request.form.get('subject_id')
            teacher_id = request.form.get('teacher_id')
            location_lat = float(request.form.get('location_lat', 0))
            location_lng = float(request.form.get('location_lng', 0))
            location_name = request.form.get('location_name')
            start_time_str = request.form.get('start_time')
            end_time_str = request.form.get('end_time')
            notes = request.form.get('notes')

            if not all([subject_id, teacher_id, start_time_str, end_time_str]):
                flash('All required fields must be filled', 'danger')
                return redirect(url_for('admin.create_session'))

            # Parse datetime
            start_time = datetime.strptime(start_time_str or '', '%Y-%m-%dT%H:%M')
            end_time = datetime.strptime(end_time_str or '', '%Y-%m-%dT%H:%M')

            # Make timezone-aware
            start_time = pytz.UTC.localize(start_time)
            end_time = pytz.UTC.localize(end_time)

            if end_time <= start_time:
                flash('End time must be after start time', 'danger')
                return redirect(url_for('admin.create_session'))

            # Create session
            session_obj = Session(subject_id=subject_id,  # type: ignore
                                  teacher_id=teacher_id,
                                  location_lat=location_lat,
                                  location_lng=location_lng,
                                  location_name=location_name,
                                  start_time=start_time,
                                  end_time=end_time,
                                  notes=notes,
                                  qr_token='temporary')

            db.session.add(session_obj)
            db.session.flush()

            # Generate actual QR token
            qr_token = generate_qr_token(session_obj.id,
                                         start_time.isoformat())
            session_obj.qr_token = qr_token

            # Save QR code image
            qr_filename = f'session_{session_obj.id}.png'
            qr_filepath = os.path.join('static', 'qr_codes', qr_filename)
            save_qr_code(qr_token, session_obj.id, qr_filepath)

            db.session.commit()

            log_audit(
                user_id=admin_user.id,
                action='SESSION_CREATED',
                entity_type='Session',
                entity_id=session_obj.id,
                details=f'Admin created session for subject ID {subject_id}',
                ip_address=request.remote_addr)

            flash('Session created successfully!', 'success')
            return redirect(url_for('admin.dashboard'))

        except Exception as e:
            db.session.rollback()
            flash(f'Error creating session: {str(e)}', 'danger')

    # Get subjects and teachers
    subjects = Subject.query.filter_by(is_active=True).all()
    teachers = User.query.filter_by(role='employee', is_active=True).all()
    return render_template('admin/create_session.html',
                           user=admin_user,
                           subjects=subjects,
                           teachers=teachers)


# Additional admin attendance tools. All endpoints require admin authorization.
from io import BytesIO, StringIO
import csv
from flask import Response, send_file
from sqlalchemy import or_


def _attendance_query():
    query = db.session.query(Attendance).join(User, Attendance.student_id == User.id).join(Session, Attendance.session_id == Session.id)
    search = request.args.get('q', '').strip()[:100]
    subject_id = request.args.get('subject_id', type=int)
    status = request.args.get('status', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    if search:
        query = query.filter(or_(User.full_name.ilike(f'%{search}%'), User.student_id.ilike(f'%{search}%')))
    if subject_id:
        query = query.filter(Attendance.subject_id == subject_id)
    if status in ('VERIFIED', 'PENDING_DURATION', 'REJECTED_DISTANCE', 'REJECTED_DUPLICATE', 'REJECTED_OTHER'):
        query = query.filter(Attendance.verification_status == status)
    try:
        if date_from:
            query = query.filter(Attendance.timestamp >= datetime.strptime(date_from, '%Y-%m-%d'))
        if date_to:
            from datetime import timedelta
            query = query.filter(Attendance.timestamp < datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1))
    except ValueError:
        query = query.filter(Attendance.id == -1)
    return query.order_by(Attendance.timestamp.desc())


@admin_bp.route('/qr-attendance')
@role_required('admin')
def qr_attendance():
    page = max(1, request.args.get('page', 1, type=int))
    sessions = Session.query.order_by(Session.start_time.desc()).paginate(page=page, per_page=25, error_out=False)
    counts = dict(db.session.query(Attendance.session_id, db.func.count(Attendance.id)).filter(Attendance.verification_status == 'VERIFIED').group_by(Attendance.session_id).all())
    return render_template('admin/qr_attendance.html', sessions=sessions, counts=counts)


@admin_bp.route('/student-records')
@role_required('admin')
def student_records():
    page = max(1, request.args.get('page', 1, type=int))
    records = _attendance_query().paginate(page=page, per_page=30, error_out=False)
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('admin/student_records.html', records=records, subjects=subjects)


def _safe_spreadsheet_value(value):
    value = str(value if value is not None else '')
    if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
        return "'" + value
    return value


@admin_bp.route('/attendance-export')
@role_required('admin')
def attendance_export():
    fmt = request.args.get('format', 'csv').lower()
    if fmt not in ('csv', 'xlsx'):
        return 'Unsupported format', 400
    headings = ['Student ID', 'Student Name', 'Department', 'Year', 'Subject', 'Session ID', 'Session Start (UTC)', 'Recorded At (UTC)', 'Status', 'Distance (m)', 'Duration (%)']
    def rows():
        yield headings
        for rec in _attendance_query().yield_per(250):
            yield [_safe_spreadsheet_value(rec.student.student_id), _safe_spreadsheet_value(rec.student.full_name), _safe_spreadsheet_value(rec.student.department), rec.student.year or '', _safe_spreadsheet_value(rec.session.subject.name), rec.session_id, rec.session.start_time.isoformat() if rec.session.start_time else '', rec.timestamp.isoformat() if rec.timestamp else '', rec.verification_status, rec.distance_meters, rec.duration_percentage if rec.duration_percentage is not None else '']
    if fmt == 'csv':
        def generate():
            out = StringIO()
            for row in rows():
                out.seek(0); out.truncate(0)
                csv.writer(out).writerow(row)
                yield out.getvalue()
        return Response(generate(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename=attendance_records.csv'})
    try:
        from openpyxl import Workbook
    except ImportError:
        flash('Excel export requires openpyxl: pip install openpyxl', 'error')
        return redirect(url_for('admin.student_records'))
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('Attendance')
    for row in rows():
        ws.append(row)
    data = BytesIO(); wb.save(data); data.seek(0)
    return send_file(data, as_attachment=True, download_name='attendance_records.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@admin_bp.route('/sessions/<int:session_id>/attendance')
@role_required('admin')
def session_attendance(session_id):
    """Accurate class-level statistics based on the subject enrollment roster."""
    item = Session.query.get_or_404(session_id)
    roster = (db.session.query(User).join(Enrollment, Enrollment.student_id == User.id)
              .filter(Enrollment.subject_id == item.subject_id, User.is_active.is_(True))
              .order_by(User.student_id).all())
    records = Attendance.query.filter_by(session_id=item.id).all()
    by_student = {r.student_id: r for r in records}
    verified = sum(1 for u in roster if u.id in by_student and by_student[u.id].verification_status == 'VERIFIED')
    total = len(roster)
    return render_template('admin/session_attendance.html', session_item=item, roster=roster,
                           by_student=by_student, enrolled_count=total, verified_count=verified,
                           absent_count=total - verified, attendance_percent=round(100 * verified / total, 1) if total else 0)



@admin_bp.route('/enrollments')
@role_required('admin')
def enrollments():

    subject_id = request.args.get('subject_id', type=int)

    subjects = (
        Subject.query
        .filter_by(is_active=True)
        .order_by(Subject.name)
        .all()
    )

    if not subject_id and subjects:
        subject_id = subjects[0].id

    selected_subject = Subject.query.filter_by(
        id=subject_id,
        is_active=True
    ).first() if subject_id else None

    if subject_id and not selected_subject:
        subject_id = subjects[0].id if subjects else None

    # Students already enrolled in selected subject
    roster = (
        db.session.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(
            Enrollment.subject_id == subject_id,
            User.is_active.is_(True)
        )
        .order_by(User.student_id)
        .all()
    ) if subject_id else []

    # Students not yet enrolled in selected subject
    available_students = (
        User.query
        .filter(
            User.role.in_(['undergraduate', 'postgraduate']),
            User.is_active.is_(True),
            ~User.id.in_(
                db.session.query(Enrollment.student_id)
                .filter(Enrollment.subject_id == subject_id)
            )
        )
        .order_by(User.full_name)
        .all()
    ) if subject_id else []

    # Active class sessions
    sessions = (
        Session.query
        .filter_by(subject_id=subject_id, is_active=True)
        .order_by(Session.start_time.desc())
        .all()
    ) if subject_id else []

    # Calculate verified attendance percentages
    verified_by_session = {
        ss.id: {
            r.student_id
            for r in Attendance.query.filter_by(
                session_id=ss.id,
                verification_status='VERIFIED'
            ).all()
        }
        for ss in sessions
    }

    percentages = {
        u.id: round(
            100 * sum(
                u.id in ids
                for ids in verified_by_session.values()
            ) / len(sessions), 1
        ) if sessions else 0
        for u in roster
    }

    return render_template(
        'admin/enrollments.html',
        subjects=subjects,
        subject_id=subject_id,
        roster=roster,
        available_students=available_students,
        sessions=sessions,
        percentages=percentages
    )

@admin_bp.route('/enrollments/assign', methods=['POST'])
@role_required('admin')
def assign_student():
    admin_user = get_current_user()
    assert admin_user is not None

    student_id = request.form.get('student_id', type=int)
    subject_id = request.form.get('subject_id', type=int)

    student = User.query.filter(
        User.id == student_id,
        User.role.in_(['undergraduate', 'postgraduate']),
        User.is_active.is_(True)
    ).first() if student_id else None

    subject = Subject.query.filter_by(
        id=subject_id,
        is_active=True
    ).first() if subject_id else None

    if not student or not subject:
        flash('Please select a valid student and subject.', 'danger')
        return redirect(url_for('admin.enrollments'))

    existing = Enrollment.query.filter_by(
        student_id=student.id,
        subject_id=subject.id
    ).first()

    if existing:
        flash('This student is already enrolled in this subject.', 'warning')
    else:
        try:
            enrollment = Enrollment(
                student_id=student.id,
                subject_id=subject.id
            )

            db.session.add(enrollment)
            db.session.flush()

            log_audit(
                user_id=admin_user.id,
                action='STUDENT_ENROLLED',
                entity_type='Enrollment',
                entity_id=enrollment.id,
                details=f'{student.full_name} assigned to {subject.name}',
                ip_address=request.remote_addr
            )

            db.session.commit()

            flash(
                f'{student.full_name} successfully assigned to {subject.name}.',
                'success'
            )

        except Exception:
            db.session.rollback()
            current_app.logger.exception('Student enrollment failed')
            flash('Could not assign student. Please try again.', 'danger')

    return redirect(url_for(
        'admin.enrollments',
        subject_id=subject_id
    ))


@admin_bp.route(
    '/enrollments/<int:enrollment_id>/remove',
    methods=['POST']
)
@role_required('admin')
def remove_enrollment(enrollment_id):

    admin_user = get_current_user()
    assert admin_user is not None

    enrollment = Enrollment.query.get_or_404(enrollment_id)
    subject_id = enrollment.subject_id

    try:
        student_name = enrollment.student.full_name
        subject_name = enrollment.subject.name

        db.session.delete(enrollment)

        log_audit(
            user_id=admin_user.id,
            action='STUDENT_UNENROLLED',
            entity_type='Enrollment',
            entity_id=enrollment_id,
            details=f'{student_name} removed from {subject_name}',
            ip_address=request.remote_addr
        )

        db.session.commit()

        flash('Student removed from subject successfully.', 'success')

    except Exception:
        db.session.rollback()
        current_app.logger.exception('Student unenrollment failed')
        flash('Could not remove student.', 'danger')

    return redirect(url_for(
        'admin.enrollments',
        subject_id=subject_id
    ))