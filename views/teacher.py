from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, send_file
from auth import login_required, role_required, get_current_user, log_audit
from models import db, Subject, Session, Attendance, User, Enrollment
from utils import generate_qr_token, save_qr_code, calculate_attendance_duration
from datetime import datetime
import pytz
import os
import openpyxl
from io import BytesIO, StringIO
import csv
from flask import current_app

teacher_bp = Blueprint('teacher', __name__, url_prefix='/teacher')

@teacher_bp.route('/dashboard')
@role_required('employee')
def dashboard():
    """Teacher dashboard"""
    user = get_current_user()
    assert user is not None
    
    # Get teacher's subjects
    subjects = Subject.query.filter_by(teacher_id=user.id, is_active=True).all()
    
    # Get upcoming sessions
    now = datetime.now(pytz.UTC)
    upcoming_sessions = Session.query.filter(
        Session.teacher_id == user.id,
        Session.start_time > now,
        Session.is_active == True
    ).order_by(Session.start_time).limit(10).all()
    
    # Get today's sessions
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    today_sessions = Session.query.filter(
        Session.teacher_id == user.id,
        Session.start_time >= today_start,
        Session.start_time <= today_end,
        Session.is_active == True
    ).order_by(Session.start_time).all()
    
    return render_template('teacher/dashboard.html',
                         user=user,
                         subjects=subjects,
                         upcoming_sessions=upcoming_sessions,
                         today_sessions=today_sessions)

@teacher_bp.route('/qr-attendance')
@role_required('employee')
def qr_attendance():
    """QR Code Attendance page - opens active session or goes to create session"""
    user = get_current_user()
    assert user is not None
    
    # Find a session that actually belongs to the signed-in professor.
    # Prefer a current class, otherwise show the latest assigned session
    # (historical demo sessions are still viewable, but not open for scanning).
    now = datetime.now(pytz.UTC)
    current_session = Session.query.filter(
        Session.teacher_id == user.id,
        Session.is_active.is_(True),
        Session.start_time <= now,
        Session.end_time >= now
    ).order_by(Session.start_time.desc()).first()
    if current_session is None:
        current_session = Session.query.filter(
            Session.teacher_id == user.id,
            Session.is_active.is_(True)
        ).order_by(Session.start_time.desc()).first()
    if current_session:
        return redirect(url_for('teacher.view_session', session_id=current_session.id))

    flash('No sessions are assigned to your account. Create a session for one of your subjects.', 'info')
    return redirect(url_for('teacher.create_session'))

@teacher_bp.route('/student-records')
@role_required('employee')
def student_records():
    """View student records for assigned subjects"""
    user = get_current_user()
    assert user is not None
    
    subjects = Subject.query.filter_by(teacher_id=user.id, is_active=True).all()
    return render_template('teacher/dashboard.html', user=user, subjects=subjects, today_sessions=[], upcoming_sessions=[])

@teacher_bp.route('/upload-attendance', methods=['GET', 'POST'])
@role_required('employee')
def upload_attendance():
    """Import a CSV roster for a teacher-owned session, recording manual status."""
    user = get_current_user()
    assert user is not None
    if request.method == 'GET':
        sessions = Session.query.filter_by(teacher_id=user.id).order_by(Session.start_time.desc()).all()
        return render_template('teacher/upload_attendance.html', user=user, sessions=sessions)

    session_id = request.form.get('session_id', type=int)
    uploaded = request.files.get('attendance_file')
    class_session = Session.query.filter_by(id=session_id, teacher_id=user.id).first() if session_id else None
    if not class_session or not uploaded or not uploaded.filename or not uploaded.filename.lower().endswith(('.csv', '.xlsx')):
        flash('Select your class session and a CSV or Excel (.xlsx) file.', 'danger')
        return redirect(url_for('teacher.upload_attendance'))
    try:
        raw = uploaded.stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('CSV exceeds 1 MB limit')
        if uploaded.filename.lower().endswith('.xlsx'):
            workbook = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=True)
            sheet = workbook.active
            values = sheet.iter_rows(values_only=True)
            headers = [str(cell).strip() if cell is not None else '' for cell in next(values, [])]
            if 'student_id' not in headers:
                workbook.close()
                raise ValueError('Excel must include a student_id column')
            reader = [dict(zip(headers, row)) for row in values]
            workbook.close()
        else:
            reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')))
            if not reader.fieldnames or 'student_id' not in reader.fieldnames:
                raise ValueError('CSV must include a student_id column')
        imported = skipped = 0
        seen = set()
        for row in reader:
            student_number = str(row.get('student_id') or '').strip()
            if not student_number or student_number in seen:
                skipped += 1
                continue
            seen.add(student_number)
            student = User.query.filter_by(student_id=student_number).first()
            if not student or not student.is_student():
                skipped += 1
                continue
            enrolled = Enrollment.query.filter_by(student_id=student.id, subject_id=class_session.subject_id).first()
            existing = Attendance.query.filter_by(student_id=student.id, session_id=class_session.id).first()
            if not enrolled or existing:
                skipped += 1
                continue
            db.session.add(Attendance(
                student_id=student.id, session_id=class_session.id,
                subject_id=class_session.subject_id,
                student_lat=0.0, student_lng=0.0, distance_meters=0.0,
                verification_status='MANUAL_PRESENT',
                rejection_reason='Manual professor import; QR and GPS not verified',
                timestamp=datetime.now(pytz.UTC), ip_address=request.remote_addr
            ))
            imported += 1
        db.session.flush()
        log_audit(user_id=user.id, action='MANUAL_ATTENDANCE_IMPORTED', entity_type='Session',
                  entity_id=class_session.id, details=f'Imported {imported}; skipped {skipped}',
                  ip_address=request.remote_addr)
        db.session.commit()
        flash(f'Imported {imported} manual records; skipped {skipped}.', 'success')
        return redirect(url_for('teacher.session_attendance', session_id=class_session.id))
    except (UnicodeDecodeError, ValueError, csv.Error, openpyxl.utils.exceptions.InvalidFileException, StopIteration) as exc:
        db.session.rollback()
        flash(f'Invalid CSV: {exc}', 'danger')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Manual attendance upload failed')
        flash('Import failed. Check the server logs.', 'danger')
    return redirect(url_for('teacher.upload_attendance'))

@teacher_bp.route('/sessions/<int:session_id>')
@role_required('employee')
def view_session(session_id):
    """View session details and QR code"""
    user = get_current_user()
    assert user is not None
    session_obj = Session.query.get_or_404(session_id)
    
    if session_obj.teacher_id != user.id:
        flash('You do not have permission to view this session', 'danger')
        return redirect(url_for('teacher.dashboard'))
    
    # Check if QR code file exists, regenerate if missing
    qr_filename = f'session_{session_obj.id}.png'
    qr_filepath = os.path.join(current_app.static_folder, 'qr_codes', qr_filename)
    
    if not os.path.exists(qr_filepath):
        try:
            qr_token = session_obj.qr_token
            if not qr_token or qr_token == 'temporary':
                qr_token = generate_qr_token(session_obj.id, session_obj.start_time.isoformat())
                session_obj.qr_token = qr_token
                db.session.commit()
            
            os.makedirs(os.path.dirname(qr_filepath), exist_ok=True)
            save_qr_code(qr_token, session_obj.id, qr_filepath)
        except Exception as e:
            flash(f'Warning: Could not generate QR code. Error: {str(e)}', 'warning')
    
    # Get attendance records
    attendance_records = Attendance.query.filter_by(session_id=session_id).all()
    
    # Count verified attendance
    verified_count = sum(1 for a in attendance_records if a.verification_status == 'VERIFIED')
    
    return render_template('teacher/view_session.html',
                         user=user,
                         class_session=session_obj,
                         attendance_records=attendance_records,
                         verified_count=verified_count)

@teacher_bp.route('/sessions/<int:session_id>/attendance')
@role_required('employee')
def session_attendance(session_id):
    """View attendance for a session"""
    user = get_current_user()
    assert user is not None
    session_obj = Session.query.get_or_404(session_id)
    
    if session_obj.teacher_id != user.id:
        flash('You do not have permission to view this session', 'danger')
        return redirect(url_for('teacher.dashboard'))
    
    attendance_records = Attendance.query.filter_by(session_id=session_id).order_by(Attendance.timestamp).all()
    
    return render_template('teacher/session_attendance.html',
                         user=user,
                         class_session=session_obj,
                         attendance_records=attendance_records)




def generate_attendance_rows(session_id):
    records = Attendance.query.filter_by(
        session_id=session_id
    ).order_by(Attendance.timestamp).all()

    headers = [
        'Student Name',
        'Student ID',
        'Email',
        'Status',
        'Distance (m)',
        'Timestamp',
        'IP Address'
    ]

    rows = []

    for r in records:
        rows.append([
            r.student.full_name,
            r.student.student_id,
            r.student.email,
            r.verification_status,
            round(r.distance_meters, 1)
            if r.verification_status == 'VERIFIED'
            and r.distance_meters is not None else '',
            r.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            if r.timestamp else '',
            r.ip_address or ''
        ])

    return headers, rows


@teacher_bp.route(
    '/sessions/<int:session_id>/export_excel',
    endpoint='export_excel'
)
@teacher_bp.route('/sessions/<int:session_id>/export_excel')
@role_required('employee')
def export_excel(session_id):

    user = get_current_user()
    assert user is not None

    class_session = Session.query.get_or_404(session_id)

    if class_session.teacher_id != user.id:
        flash('You do not have permission to export this session', 'danger')
        return redirect(url_for('teacher.dashboard'))

    headers, rows = generate_attendance_rows(session_id)

    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = 'Attendance Records'

    worksheet.append(headers)

    for row in rows:
        worksheet.append(row)

    # Professional formatting
    worksheet.freeze_panes = 'A2'
    worksheet.auto_filter.ref = worksheet.dimensions

    for column in worksheet.columns:
        max_length = max(
            len(str(cell.value or '')) for cell in column
        )
        worksheet.column_dimensions[
            column[0].column_letter
        ].width = min(max_length + 4, 35)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    log_audit(
        user_id=user.id,
        action='ATTENDANCE_EXPORTED',
        entity_type='Session',
        entity_id=session_id,
        details='Exported Excel attendance',
        ip_address=request.remote_addr
    )

    filename = (
        f'attendance_session_{session_id}_'
        f'{datetime.now().strftime("%Y%m%d")}.xlsx'
    )

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@teacher_bp.route(
    '/sessions/<int:session_id>/export_csv',
    endpoint='export_csv'
)
@role_required('employee')
def export_csv(session_id):

    user = get_current_user()
    assert user is not None

    class_session = Session.query.get_or_404(session_id)

    if class_session.teacher_id != user.id:
        flash('You do not have permission to export this session', 'danger')
        return redirect(url_for('teacher.dashboard'))

    headers, rows = generate_attendance_rows(session_id)

    output = StringIO()
    writer = csv.writer(output)

    writer.writerow(headers)
    writer.writerows(rows)

    file_output = BytesIO(
        output.getvalue().encode('utf-8-sig')
    )

    log_audit(
        user_id=user.id,
        action='ATTENDANCE_EXPORTED',
        entity_type='Session',
        entity_id=session_id,
        details='Exported CSV attendance',
        ip_address=request.remote_addr
    )

    filename = (
        f'attendance_session_{session_id}_'
        f'{datetime.now().strftime("%Y%m%d")}.csv'
    )

    return send_file(
        file_output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@teacher_bp.route('/sessions/create', methods=['GET', 'POST'])
@role_required('employee')
def create_session():
    """Employee creates a new session for their subjects"""
    user = get_current_user()
    assert user is not None
    
    if request.method == 'POST':
        try:
            subject_id = request.form.get('subject_id')
            location_lat = float(request.form.get('location_lat', 0))
            location_lng = float(request.form.get('location_lng', 0))
            location_name = request.form.get('location_name')
            start_time_str = request.form.get('start_time')
            end_time_str = request.form.get('end_time')
            notes = request.form.get('notes')
            is_compensation = request.form.get('is_compensation') == 'on'
            compensates_session_id = request.form.get('compensates_session_id')
            
            if not all([subject_id, start_time_str, end_time_str]):
                flash('All required fields must be filled', 'danger')
                return redirect(url_for('teacher.create_session'))
            
            # Verify teacher owns this subject
            subject = Subject.query.get(subject_id)
            if not subject or subject.teacher_id != user.id:
                flash('You can only create sessions for your own subjects', 'danger')
                return redirect(url_for('teacher.create_session'))
            
            # Parse datetime
            start_time = datetime.strptime(start_time_str or '', '%Y-%m-%dT%H:%M')
            end_time = datetime.strptime(end_time_str or '', '%Y-%m-%dT%H:%M')
            
            # Make timezone-aware
            start_time = pytz.UTC.localize(start_time)
            end_time = pytz.UTC.localize(end_time)
            
            if end_time <= start_time:
                flash('End time must be after start time', 'danger')
                return redirect(url_for('teacher.create_session'))
            
            # Create session
            session_obj = Session(
                subject_id=subject_id,
                teacher_id=user.id,
                location_lat=location_lat,
                location_lng=location_lng,
                location_name=location_name,
                start_time=start_time,
                end_time=end_time,
                notes=notes,
                is_compensation=is_compensation,
                compensates_session_id=int(compensates_session_id) if compensates_session_id else None,
                qr_token='temporary'
            )
            
            db.session.add(session_obj)
            db.session.flush()
            
            # Generate actual QR token
            qr_token = generate_qr_token(session_obj.id, start_time.isoformat())
            session_obj.qr_token = qr_token
            
            # Save QR code image
            qr_filename = f'session_{session_obj.id}.png'
            qr_filepath = os.path.join(current_app.static_folder, 'qr_codes', qr_filename)
            save_qr_code(qr_token, session_obj.id, qr_filepath)
            
            db.session.commit()
            
            log_audit(
                user_id=user.id,
                action='SESSION_CREATED',
                entity_type='Session',
                entity_id=session_obj.id,
                details=f'Teacher created session for {subject.name}' + (' (Compensation)' if is_compensation else ''),
                ip_address=request.remote_addr
            )
            
            flash(f'Session created successfully! Session ID: {session_obj.id}', 'success')
            return redirect(url_for('teacher.view_session', session_id=session_obj.id))
            
        except ValueError as e:
            flash(f'Invalid input: {str(e)}', 'danger')
            return redirect(url_for('teacher.create_session'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating session: {str(e)}', 'danger')
            return redirect(url_for('teacher.create_session'))
    
    # GET request - show form
    subjects = Subject.query.filter_by(teacher_id=user.id, is_active=True).all()
    
    # Get past sessions that could be compensated
    past_sessions = Session.query.filter(
        Session.teacher_id == user.id,
        Session.end_time < datetime.now(pytz.UTC),
        Session.is_active == True
    ).order_by(Session.start_time.desc()).limit(20).all()
    
    return render_template('teacher/create_session.html', 
                         user=user, 
                         subjects=subjects,
                         past_sessions=past_sessions)

@teacher_bp.route('/sessions/<int:session_id>/calculate_duration', methods=['POST'])
@role_required('employee')
def calculate_duration(session_id):
    """Calculate attendance duration for a completed session"""
    user = get_current_user()
    assert user is not None
    session_obj = Session.query.get_or_404(session_id)
    
    if session_obj.teacher_id != user.id:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    
    success, message, count = calculate_attendance_duration(session_id)
    
    if success:
        log_audit(
            user_id=user.id,
            action='DURATION_CALCULATED',
            entity_type='Session',
            entity_id=session_id,
            details=f'Calculated duration for {count} attendance records',
            ip_address=request.remote_addr
        )
        return jsonify({'success': True, 'message': message, 'updated_count': count})
    else:
        return jsonify({'success': False, 'message': message}), 400

@teacher_bp.route('/sessions/<int:session_id>/refresh_qr')
@role_required('employee')
def refresh_qr(session_id):
    """Regenerate QR code with new timestamp"""
    user = get_current_user()
    assert user is not None
    session_obj = Session.query.get_or_404(session_id)
    
    if session_obj.teacher_id != user.id:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        current_time = datetime.now(pytz.UTC).isoformat()
        qr_token = generate_qr_token(session_obj.id, current_time)
        session_obj.qr_token = qr_token
        
        qr_filename = f'session_{session_obj.id}.png'
        qr_filepath = os.path.join(current_app.static_folder, 'qr_codes', qr_filename)
        save_qr_code(qr_token, session_obj.id, qr_filepath)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'qr_url': url_for('static', filename=f'qr_codes/{qr_filename}'),
            'timestamp': current_time
        })
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500