from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for, current_app
from auth import login_required, role_required, get_current_user, log_audit
from models import db, Session, Attendance, Subject, Enrollment
from utils import validate_qr_token, verify_location, get_daily_attendance_summary, get_weekly_attendance_summary
from extensions import csrf
from datetime import datetime
import pytz

student_bp = Blueprint('student', __name__, url_prefix='/student')

def _report_date_for_student(student_id):
    """Use most recent enrolled class date for demo when no date is supplied."""
    last_session = (Session.query.join(Enrollment, Enrollment.subject_id == Session.subject_id)
        .filter(Enrollment.student_id == student_id, Session.is_active.is_(True),
                Session.end_time <= datetime.now(pytz.UTC).replace(tzinfo=None))
        .order_by(Session.start_time.desc()).first())
    return pytz.UTC.localize(last_session.start_time) if last_session else datetime.now(pytz.UTC)


@student_bp.route('/dashboard')
@role_required('undergraduate', 'postgraduate')
def dashboard():
    """Student dashboard showing today's attendance"""
    user = get_current_user()
    assert user is not None
    today = datetime.now(pytz.UTC)
    
    # Get daily summary
    report_date = _report_date_for_student(user.id)
    daily_summary = get_daily_attendance_summary(user.id, report_date)
    
    # Get weekly summary
    weekly_summary = get_weekly_attendance_summary(user.id, report_date)
    
    # All-time history is separate from today's/this week's attendance.
    # Only enrolled subjects and completed sessions count toward a percentage.
    from sqlalchemy import func
    enrolled_subjects = (db.session.query(Subject)
        .join(Enrollment, Enrollment.subject_id == Subject.id)
        .filter(Enrollment.student_id == user.id)
        .order_by(Subject.name).all())
    now = datetime.now(pytz.UTC).replace(tzinfo=None)
    subject_attendance = []
    for subject in enrolled_subjects:
        completed = Session.query.filter(
            Session.subject_id == subject.id,
            Session.is_active.is_(True),
            Session.end_time <= now
        ).all()
        ids = [item.id for item in completed]
        present = (Attendance.query.filter(
            Attendance.student_id == user.id,
            Attendance.session_id.in_(ids),
            Attendance.verification_status == 'VERIFIED'
        ).count()) if ids else 0
        subject_attendance.append({
            'subject': subject,
            'total': len(ids),
            'present': present,
            'absent': len(ids) - present,
            'percentage': round(present / len(ids) * 100, 1) if ids else 0
        })
    total_classes = sum(x['total'] for x in subject_attendance)
    total_present = sum(x['present'] for x in subject_attendance)
    overall_percentage = round(total_present / total_classes * 100, 1) if total_classes else 0

    return render_template('student/dashboard.html',
                         user=user,
                         daily_summary=daily_summary,
                         weekly_summary=weekly_summary,
                         today=today,
                         report_date=report_date,
                         subject_attendance=subject_attendance,
                         overall_percentage=overall_percentage,
                         total_classes=total_classes,
                         total_present=total_present)

@student_bp.route('/scan')
@role_required('undergraduate', 'postgraduate')
def scan_qr():
    """QR code scanning page"""
    user = get_current_user()
    return render_template('student/scan_qr.html', user=user)

@student_bp.route('/attendance/mark', methods=['POST'])
@csrf.exempt
@role_required('undergraduate', 'postgraduate')
def mark_attendance():
    """Mark attendance via QR code scan"""
    user = get_current_user()
    assert user is not None
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        qr_token = data.get('token')
        latitude_str = data.get('latitude')
        longitude_str = data.get('longitude')
        
        # Validate required fields
        if not qr_token:
            return jsonify({'success': False, 'message': 'QR token is required'}), 400
        
        if not latitude_str or not longitude_str:
            return jsonify({
                'success': False, 
                'message': 'Location is required. Please enable location permissions in your browser settings and try again.'
            }), 400
        
        # Validate and convert coordinates
        try:
            student_lat = float(latitude_str)
            student_lng = float(longitude_str)
        except (ValueError, TypeError):
            return jsonify({
                'success': False,
                'message': 'Invalid location coordinates. Please ensure location services are enabled and try again.'
            }), 400
        
        # Decode token to get session ID (basic extraction, validation happens next)
        import base64
        try:
            token_data = base64.urlsafe_b64decode(qr_token.encode('utf-8')).decode('utf-8')
            session_id = int(token_data.split('|')[0])
        except:
            return jsonify({'success': False, 'message': 'Invalid QR code format'}), 400
        
        # Get session
        session_obj = Session.query.get(session_id)
        if not session_obj:
            return jsonify({'success': False, 'message': 'Session not found'}), 404
        
        # Validate QR token
        is_valid, error_msg = validate_qr_token(qr_token, session_id, expiry_minutes=30)
        if not is_valid:
            log_audit(
                user_id=user.id,
                action='ATTENDANCE_REJECTED',
                entity_type='Session',
                entity_id=session_id,
                details=f'Invalid token: {error_msg}',
                ip_address=request.remote_addr
            )
            return jsonify({'success': False, 'message': error_msg}), 400
        
        # Check if already marked attendance
        existing = Attendance.query.filter_by(
            student_id=user.id,
            session_id=session_id
        ).first()
        
        if existing:
            if existing.verification_status == 'VERIFIED':
                return jsonify({'success': False, 'message': 'Attendance already marked for this session'}), 400
            else:
                return jsonify({'success': False, 'message': f'Previous attendance attempt was rejected: {existing.rejection_reason}'}), 400
        
        # Verify location
        is_location_valid, distance, location_msg = verify_location(
            session_obj.location_lat,
            session_obj.location_lng,
            student_lat,
            student_lng,
            max_distance_meters=100
        )
        
        # Create attendance record
        now = datetime.now(pytz.UTC)
        
        # Calculate duration percentage if session has started
        duration_percentage = None
        verification_status = 'VERIFIED' if is_location_valid else 'REJECTED_DISTANCE'
        
        if is_location_valid and session_obj.is_ongoing():
            # Session is ongoing - mark as PENDING_DURATION until we can verify they stayed
            # Calculate how much of the session has elapsed when they checked in
            session_duration = (session_obj.end_time - session_obj.start_time).total_seconds()
            time_elapsed_at_checkin = (now - session_obj.start_time).total_seconds()
            
            # If they checked in during the first 20% of the session, they can potentially get full attendance
            # Otherwise, their max possible attendance is reduced
            if time_elapsed_at_checkin / session_duration <= 0.2:
                # Checked in early, status will be VERIFIED after session ends if they stay
                verification_status = 'VERIFIED'
            else:
                # Checked in late - for now mark as verified but duration_percentage will be calculated later
                verification_status = 'VERIFIED'
        
        if not Enrollment.query.filter_by(student_id=user.id, subject_id=session_obj.subject_id).first():
            return jsonify({'success': False, 'message': 'You are not enrolled in this subject.'}), 403

        attendance = Attendance(  # type: ignore
            student_id=user.id,
            session_id=session_id,
            subject_id=session_obj.subject_id,
            student_lat=student_lat,
            student_lng=student_lng,
            distance_meters=distance if distance else 0,
            verification_status=verification_status,
            timestamp=now,
            check_in_time=now if is_location_valid else None,
            duration_percentage=duration_percentage,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:255],
            rejection_reason=None if is_location_valid else location_msg
        )
        
        db.session.add(attendance)
        db.session.commit()
        
        # Log audit
        log_audit(
            user_id=user.id,
            action='ATTENDANCE_MARKED' if is_location_valid else 'ATTENDANCE_REJECTED',
            entity_type='Session',
            entity_id=session_id,
            details=f'Distance: {distance:.1f}m, Status: {attendance.verification_status}',
            ip_address=request.remote_addr
        )
        
        if is_location_valid:
            return jsonify({
                'success': True,
                'message': f'Attendance marked successfully! Distance: {distance:.1f}m',
                'attendance_id': attendance.id
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': f'Attendance rejected: {location_msg}',
                'distance': f'{distance:.1f}m' if distance else 'unknown'
            }), 400
    
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error marking attendance: {str(e)}'}), 500

@student_bp.route('/attendance/daily')
@role_required('undergraduate', 'postgraduate')
def daily_attendance():
    """View daily attendance"""
    user = get_current_user()
    assert user is not None
    
    # Get date from query parameter or use today
    date_str = request.args.get('date')
    if date_str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            date = pytz.UTC.localize(date)
        except:
            date = _report_date_for_student(user.id)
    else:
        date = _report_date_for_student(user.id)
    
    summary = get_daily_attendance_summary(user.id, date)
    
    return render_template('student/daily_attendance.html',
                         user=user,
                         summary=summary,
                         date=date)

@student_bp.route('/attendance/weekly')
@role_required('undergraduate', 'postgraduate')
def weekly_attendance():
    """View weekly attendance"""
    user = get_current_user()
    assert user is not None
    
    # Get date from query parameter or use today
    date_str = request.args.get('date')
    if date_str:
        try:
            date = datetime.strptime(date_str, '%Y-%m-%d')
            date = pytz.UTC.localize(date)
        except:
            date = _report_date_for_student(user.id)
    else:
        date = _report_date_for_student(user.id)
    
    summary = get_weekly_attendance_summary(user.id, date)
    
    return render_template('student/weekly_attendance.html',
                         user=user,
                         summary=summary,
                         date=date)
