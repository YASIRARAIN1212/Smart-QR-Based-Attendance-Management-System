from extensions import csrf
import base64
import binascii

from flask import (
    Blueprint, render_template, request,
    jsonify, flash, redirect, url_for, current_app
)

from auth import role_required, get_current_user, log_audit
from models import db, Session, Attendance, Subject, Enrollment
from utils import (
    validate_qr_token,
    verify_location,
    get_daily_attendance_summary,
    get_weekly_attendance_summary
)

from datetime import datetime
import pytz


student_bp = Blueprint(
    'student',
    __name__,
    url_prefix='/student'
)


# =====================================================
# REPORT DATE
# =====================================================

def _report_date_for_student(student_id):

    last_session = (
        Session.query
        .join(
            Enrollment,
            Enrollment.subject_id == Session.subject_id
        )
        .filter(
            Enrollment.student_id == student_id,
            Session.is_active.is_(True),
            Session.end_time <= datetime.now(pytz.UTC).replace(
                tzinfo=None
            )
        )
        .order_by(Session.start_time.desc())
        .first()
    )

    if last_session:
        dt = last_session.start_time

        if dt.tzinfo is None:
            return pytz.UTC.localize(dt)

        return dt.astimezone(pytz.UTC)

    return datetime.now(pytz.UTC)


# =====================================================
# STUDENT DASHBOARD
# =====================================================

@student_bp.route('/dashboard')
@role_required('undergraduate', 'postgraduate')
def dashboard():

    user = get_current_user()
    assert user is not None

    today = datetime.now(pytz.UTC)

    report_date = _report_date_for_student(user.id)

    daily_summary = get_daily_attendance_summary(
        user.id,
        report_date
    )

    weekly_summary = get_weekly_attendance_summary(
        user.id,
        report_date
    )

    enrolled_subjects = (
        db.session.query(Subject)
        .join(
            Enrollment,
            Enrollment.subject_id == Subject.id
        )
        .filter(Enrollment.student_id == user.id)
        .order_by(Subject.name)
        .all()
    )

    now = datetime.now(pytz.UTC).replace(tzinfo=None)

    subject_attendance = []

    for subject in enrolled_subjects:

        completed = Session.query.filter(
            Session.subject_id == subject.id,
            Session.is_active.is_(True),
            Session.end_time <= now
        ).all()

        ids = [item.id for item in completed]

        present = 0

        if ids:

            present = Attendance.query.filter(
                Attendance.student_id == user.id,
                Attendance.session_id.in_(ids),
                Attendance.verification_status == 'VERIFIED'
            ).count()

        total = len(ids)

        subject_attendance.append({
            'subject': subject,
            'total': total,
            'present': present,
            'absent': total - present,
            'percentage': (
                round(present / total * 100, 1)
                if total else 0
            )
        })

    total_classes = sum(
        item['total'] for item in subject_attendance
    )

    total_present = sum(
        item['present'] for item in subject_attendance
    )

    overall_percentage = (
        round(total_present / total_classes * 100, 1)
        if total_classes else 0
    )

    return render_template(
        'student/dashboard.html',
        user=user,
        daily_summary=daily_summary,
        weekly_summary=weekly_summary,
        today=today,
        report_date=report_date,
        subject_attendance=subject_attendance,
        overall_percentage=overall_percentage,
        total_classes=total_classes,
        total_present=total_present
    )


# =====================================================
# QR SCANNER PAGE
# =====================================================

@student_bp.route('/scan')
@role_required('undergraduate', 'postgraduate')
def scan_qr():

    user = get_current_user()

    return render_template(
        'student/scan_qr.html',
        user=user
    )


# =====================================================
# MARK ATTENDANCE THROUGH QR
# =====================================================

@student_bp.route(
    '/attendance/mark',
    methods=['POST']
)
@csrf.exempt
@role_required('undergraduate', 'postgraduate')
def mark_attendance():

    user = get_current_user()
    assert user is not None

    try:

        data = request.get_json(silent=True)

        if not data:

            return jsonify({
                'success': False,
                'message': 'No data provided.'
            }), 400

        qr_token = data.get('token')

        latitude_str = data.get('latitude')
        longitude_str = data.get('longitude')

        # ---------------------------------------------
        # CHECK REQUIRED VALUES
        # ---------------------------------------------

        if not qr_token or not isinstance(qr_token, str):

            return jsonify({
                'success': False,
                'message': 'QR token is required.'
            }), 400

        if not latitude_str or not longitude_str:

            return jsonify({
                'success': False,
                'message': (
                    'Location is required. Please enable '
                    'location permissions in your browser.'
                )
            }), 400

        # ---------------------------------------------
        # VALIDATE GPS COORDINATES
        # ---------------------------------------------

        try:

            student_lat = float(latitude_str)
            student_lng = float(longitude_str)

            if not (
                -90 <= student_lat <= 90
                and -180 <= student_lng <= 180
            ):

                raise ValueError('Coordinates outside valid range.')

        except (ValueError, TypeError):

            return jsonify({
                'success': False,
                'message': 'Invalid GPS coordinates.'
            }), 400

        # ---------------------------------------------
        # DECODE QR TOKEN
        # ---------------------------------------------

        try:

            decoded = base64.urlsafe_b64decode(
                qr_token.encode('utf-8')
            ).decode('utf-8')

            parts = decoded.split('|')

            if len(parts) != 3:
                raise ValueError('Invalid token structure.')

            session_id = int(parts[0])

            if session_id <= 0:
                raise ValueError('Invalid session ID.')

        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error
        ):

            return jsonify({
                'success': False,
                'message': 'Invalid QR code format.'
            }), 400

        # ---------------------------------------------
        # FIND SESSION
        # ---------------------------------------------

        session_obj = db.session.get(Session, session_id)

        if not session_obj:

            return jsonify({
                'success': False,
                'message': 'Session not found.'
            }), 404

        if not session_obj.is_active:

            return jsonify({
                'success': False,
                'message': 'This attendance session is inactive.'
            }), 400

        # ---------------------------------------------
        # CHECK ENROLLMENT
        # ---------------------------------------------

        enrollment = Enrollment.query.filter_by(
            student_id=user.id,
            subject_id=session_obj.subject_id
        ).first()

        if not enrollment:

            return jsonify({
                'success': False,
                'message': 'You are not enrolled in this subject.'
            }), 403

        # ---------------------------------------------
        # VERIFY QR SIGNATURE AND EXPIRY
        # ---------------------------------------------

        is_valid, error_msg = validate_qr_token(
            qr_token,
            session_id,
            expiry_minutes=30
        )

        if not is_valid:

            log_audit(
                user_id=user.id,
                action='ATTENDANCE_REJECTED',
                entity_type='Session',
                entity_id=session_id,
                details=f'Invalid QR token: {error_msg}',
                ip_address=request.remote_addr
            )

            return jsonify({
                'success': False,
                'message': error_msg
            }), 400

        # ---------------------------------------------
        # CHECK EXISTING ATTENDANCE
        # ---------------------------------------------

        existing = Attendance.query.filter_by(
            student_id=user.id,
            session_id=session_id
        ).first()

        if existing:

            if existing.verification_status in (
                'VERIFIED',
                'MANUAL_PRESENT',
                'PENDING_DURATION'
            ):

                return jsonify({
                    'success': False,
                    'message': (
                        'Attendance already marked for this session.'
                    )
                }), 400

            return jsonify({
                'success': False,
                'message': (
                    'A previous attendance attempt already exists: '
                    + str(existing.rejection_reason or 'Rejected')
                )
            }), 400

        # ---------------------------------------------
        # VERIFY LOCATION - 100 METRES
        # ---------------------------------------------

        is_location_valid, distance, location_msg = verify_location(
            session_obj.location_lat,
            session_obj.location_lng,
            student_lat,
            student_lng,
            max_distance_meters=100
        )

        # ---------------------------------------------
        # CREATE ATTENDANCE RECORD
        # ---------------------------------------------

        now = datetime.now(pytz.UTC)

        verification_status = (
            'VERIFIED'
            if is_location_valid
            else 'REJECTED_DISTANCE'
        )

        duration_percentage = None

        if is_location_valid and session_obj.is_ongoing():

            verification_status = 'VERIFIED'

        attendance = Attendance(

            student_id=user.id,

            session_id=session_id,

            subject_id=session_obj.subject_id,

            student_lat=student_lat,

            student_lng=student_lng,

            distance_meters=(
                distance if distance is not None else 0
            ),

            verification_status=verification_status,

            timestamp=now,

            check_in_time=(
                now if is_location_valid else None
            ),

            duration_percentage=duration_percentage,

            ip_address=request.remote_addr,

            user_agent=request.headers.get(
                'User-Agent', ''
            )[:255],

            rejection_reason=(
                None if is_location_valid else location_msg
            )
        )

        db.session.add(attendance)

        db.session.flush()

        # ---------------------------------------------
        # AUDIT LOG
        # ---------------------------------------------

        log_audit(
            user_id=user.id,

            action=(
                'ATTENDANCE_MARKED'
                if is_location_valid
                else 'ATTENDANCE_REJECTED'
            ),

            entity_type='Session',

            entity_id=session_id,

            details=(
                f'Distance: {distance:.1f}m, '
                f'Status: {attendance.verification_status}'
            ),

            ip_address=request.remote_addr
        )

        db.session.commit()

        # ---------------------------------------------
        # SUCCESS RESPONSE
        # ---------------------------------------------

        if is_location_valid:

            return jsonify({

                'success': True,

                'message': (
                    'Attendance marked successfully! '
                    f'Distance: {distance:.1f}m'
                ),

                'attendance_id': attendance.id

            }), 200

        return jsonify({

            'success': False,

            'message': (
                f'Attendance rejected: {location_msg}'
            ),

            'distance': (
                f'{distance:.1f}m'
                if distance is not None
                else 'unknown'
            )

        }), 400

    except Exception:

        db.session.rollback()

        current_app.logger.exception(
            'Student attendance marking failed'
        )

        return jsonify({
            'success': False,
            'message': (
                'An unexpected error occurred. '
                'Please try again.'
            )
        }), 500


# =====================================================
# DAILY ATTENDANCE
# =====================================================

@student_bp.route('/attendance/daily')
@role_required('undergraduate', 'postgraduate')
def daily_attendance():

    user = get_current_user()
    assert user is not None

    date_str = request.args.get('date')

    if date_str:

        try:

            date = datetime.strptime(
                date_str,
                '%Y-%m-%d'
            )

            date = pytz.UTC.localize(date)

        except ValueError:

            date = _report_date_for_student(user.id)

    else:

        date = _report_date_for_student(user.id)

    summary = get_daily_attendance_summary(
        user.id,
        date
    )

    return render_template(
        'student/daily_attendance.html',
        user=user,
        summary=summary,
        date=date
    )


# =====================================================
# WEEKLY ATTENDANCE
# =====================================================

@student_bp.route('/attendance/weekly')
@role_required('undergraduate', 'postgraduate')
def weekly_attendance():

    user = get_current_user()
    assert user is not None

    date_str = request.args.get('date')

    if date_str:

        try:

            date = datetime.strptime(
                date_str,
                '%Y-%m-%d'
            )

            date = pytz.UTC.localize(date)

        except ValueError:

            date = _report_date_for_student(user.id)

    else:

        date = _report_date_for_student(user.id)

    summary = get_weekly_attendance_summary(
        user.id,
        date
    )

    return render_template(
        'student/weekly_attendance.html',
        user=user,
        summary=summary,
        date=date
    )
