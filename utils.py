import os
import hmac
import hashlib
import base64
import qrcode
from io import BytesIO
from datetime import datetime, timedelta
import pytz
from geopy.distance import geodesic
from flask import current_app
import secrets

def generate_qr_token(session_id, timestamp=None):
    """
    Generate a secure QR token with HMAC signature
    Format: base64(session_id|timestamp|HMAC(session_id|timestamp, SECRET_KEY))
    """
    if timestamp is None:
        timestamp = datetime.now(pytz.UTC).isoformat()
    
    secret_key = current_app.config['SECRET_KEY'].encode('utf-8')
    message = f"{session_id}|{timestamp}".encode('utf-8')
    
    signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
    token_data = f"{session_id}|{timestamp}|{signature}"
    
    token = base64.urlsafe_b64encode(token_data.encode('utf-8')).decode('utf-8')
    return token

def validate_qr_token(token, session_id, expiry_minutes=30):
    """
    Validate a QR token and check if it matches the session and hasn't expired
    Returns: (is_valid, error_message)
    """
    try:
        token_data = base64.urlsafe_b64decode(token.encode('utf-8')).decode('utf-8')
        parts = token_data.split('|')
        
        if len(parts) != 3:
            return False, "Invalid token format"
        
        token_session_id, token_timestamp, token_signature = parts
        
        # Verify session ID matches
        if str(token_session_id) != str(session_id):
            return False, "Token does not match this session"
        
        # Verify HMAC signature
        secret_key = current_app.config['SECRET_KEY'].encode('utf-8')
        message = f"{token_session_id}|{token_timestamp}".encode('utf-8')
        expected_signature = hmac.new(secret_key, message, hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(token_signature, expected_signature):
            return False, "Invalid token signature"
        
        # Check expiry
        token_time = datetime.fromisoformat(token_timestamp)
        now = datetime.now(pytz.UTC)
        
        # Make token_time timezone-aware if it isn't
        if token_time.tzinfo is None:
            token_time = pytz.UTC.localize(token_time)
        
        time_diff = abs((now - token_time).total_seconds() / 60)
        
        if time_diff > expiry_minutes:
            return False, f"Token expired (valid for {expiry_minutes} minutes)"
        
        return True, "Token is valid"
    
    except Exception as e:
        return False, f"Token validation error: {str(e)}"

def generate_qr_code(token, session_id):
    """
    Generate a QR code image for a session token
    Returns: BytesIO object containing PNG image
    """
    qr = qrcode.QRCode(  # type: ignore
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,  # type: ignore
        box_size=10,
        border=4,
    )
    
    qr.add_data(token)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save to BytesIO
    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    return img_io

def save_qr_code(token, session_id, filepath):
    """
    Save a QR code image to a file
    """
    img_io = generate_qr_code(token, session_id)
    
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    
    with open(filepath, 'wb') as f:
        f.write(img_io.getvalue())
    
    return filepath

def calculate_distance(lat1, lng1, lat2, lng2):
    """
    Calculate distance between two GPS coordinates in meters
    Uses geopy's geodesic distance calculation
    """
    try:
        coord1 = (lat1, lng1)
        coord2 = (lat2, lng2)
        distance = geodesic(coord1, coord2).meters
        return distance
    except Exception as e:
        raise ValueError(f"Error calculating distance: {str(e)}")

def verify_location(session_lat, session_lng, student_lat, student_lng, max_distance_meters=100):
    """
    Verify if student is within allowed distance of session location
    Returns: (is_valid, distance_meters, message)
    """
    try:
        distance = calculate_distance(session_lat, session_lng, student_lat, student_lng)
        
        if distance <= max_distance_meters:
            return True, distance, "Location verified"
        else:
            return False, distance, f"Too far from session location ({distance:.1f}m > {max_distance_meters}m)"
    
    except Exception as e:
        return False, None, f"Location verification error: {str(e)}"

def calculate_attendance_duration(session_id):
    """
    Calculate duration percentage for all attendance records of a completed session
    Updates verification status based on 80% minimum attendance requirement
    Returns: (success, message, updated_count)
    """
    try:
        from models import Session, Attendance, db
        from datetime import datetime
        import pytz
        
        session_obj = Session.query.get(session_id)
        if not session_obj:
            return False, "Session not found", 0
        
        # Only process past sessions
        now = datetime.now(pytz.UTC)
        if not session_obj.is_past():
            return False, "Session has not ended yet", 0
        
        # Get all attendance records for this session
        attendance_records = Attendance.query.filter_by(session_id=session_id).all()
        
        if not attendance_records:
            return True, "No attendance records to process", 0
        
        # Calculate session duration
        session_duration = (session_obj.end_time - session_obj.start_time).total_seconds()
        
        if session_duration <= 0:
            return False, "Invalid session duration", 0
        
        updated_count = 0
        
        for attendance in attendance_records:
            # Skip rejected records
            if attendance.verification_status.startswith('REJECTED'):
                continue
            
            # If no check_in_time, use timestamp
            check_in = attendance.check_in_time or attendance.timestamp
            
            # If check-out time exists, use it; otherwise assume they stayed until session end
            check_out = attendance.check_out_time or session_obj.end_time
            
            # Ensure check_out doesn't exceed session end
            if check_out > session_obj.end_time:
                check_out = session_obj.end_time
            
            # Ensure check_in is at least session start
            if check_in < session_obj.start_time:
                check_in = session_obj.start_time
            
            # Calculate duration student was present
            time_present = (check_out - check_in).total_seconds()
            
            # Calculate percentage
            duration_percentage = (time_present / session_duration) * 100
            
            # Cap at 100%
            duration_percentage = min(duration_percentage, 100.0)
            
            # Update attendance record
            attendance.duration_percentage = duration_percentage
            
            # Apply 80% threshold
            if duration_percentage >= 80.0:
                attendance.verification_status = 'VERIFIED'
                attendance.rejection_reason = None
            else:
                attendance.verification_status = 'REJECTED_DURATION'
                attendance.rejection_reason = f'Attended only {duration_percentage:.1f}% of session (minimum 80% required)'
            
            updated_count += 1
        
        db.session.commit()
        
        return True, f"Updated {updated_count} attendance records", updated_count
    
    except Exception as e:
        from models import db
        db.session.rollback()
        return False, f"Error calculating duration: {str(e)}", 0

def format_datetime_local(dt, timezone_str='UTC'):
    """
    Format datetime for display in local timezone
    """
    if dt is None:
        return ''
    
    # Ensure dt is timezone-aware
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    
    tz = pytz.timezone(timezone_str)
    local_dt = dt.astimezone(tz)
    
    return local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')

def get_week_date_range(date=None):
    """
    Get the start and end dates for a week (Monday to Sunday)
    """
    if date is None:
        date = datetime.now(pytz.UTC)
    
    # Ensure date is timezone-aware
    if date.tzinfo is None:
        date = pytz.UTC.localize(date)
    
    # Get Monday of the week
    start = date - timedelta(days=date.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get Sunday of the week
    end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    
    return start, end

def get_daily_attendance_summary(student_id, date=None):
    """
    Get attendance summary for a student for a specific day
    Returns: {
        'total_sessions': int,
        'attended': int,
        'missed': int,
        'percentage': float,
        'sessions': [list of session details]
    }
    """
    from models import Session, Attendance, Enrollment, db
    
    if date is None:
        date = datetime.now(pytz.UTC)
    
    # Ensure date is timezone-aware
    if date.tzinfo is None:
        date = pytz.UTC.localize(date)
    
    # Get start and end of day
    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Get all sessions for the day
    sessions = Session.query.filter(
        Session.start_time >= start_of_day.replace(tzinfo=None),
        Session.start_time <= end_of_day.replace(tzinfo=None),
        Session.end_time <= datetime.now(pytz.UTC).replace(tzinfo=None),
        Session.is_active == True,
        Session.subject_id.in_(db.session.query(Enrollment.subject_id).filter(Enrollment.student_id == student_id))
    ).all()
    
    total_sessions = len(sessions)
    attended = 0
    session_details = []
    
    for sess in sessions:
        attendance = Attendance.query.filter_by(
            student_id=student_id,
            session_id=sess.id,
            verification_status='VERIFIED'
        ).first()
        
        is_attended = attendance is not None
        if is_attended:
            attended += 1
        
        session_details.append({
            'session': sess,
            'attended': is_attended,
            'attendance_record': attendance
        })
    
    missed = total_sessions - attended
    percentage = (attended / total_sessions * 100) if total_sessions > 0 else 0
    
    return {
        'total_sessions': total_sessions,
        'attended': attended,
        'missed': missed,
        'percentage': round(percentage, 2),
        'sessions': session_details
    }

def get_weekly_attendance_summary(student_id, start_date=None):
    """
    Get attendance summary for a student for a week
    """
    from models import Session, Attendance, Enrollment, db
    
    if start_date is None:
        start_date = datetime.now(pytz.UTC)
    
    week_start, week_end = get_week_date_range(start_date)
    
    # Get all sessions for the week
    sessions = Session.query.filter(
        Session.start_time >= week_start.replace(tzinfo=None),
        Session.start_time <= week_end.replace(tzinfo=None),
        Session.end_time <= datetime.now(pytz.UTC).replace(tzinfo=None),
        Session.is_active == True,
        Session.subject_id.in_(db.session.query(Enrollment.subject_id).filter(Enrollment.student_id == student_id))
    ).all()
    
    total_sessions = len(sessions)
    attended = 0
    missed_sessions = []
    
    for sess in sessions:
        attendance = Attendance.query.filter_by(
            student_id=student_id,
            session_id=sess.id,
            verification_status='VERIFIED'
        ).first()
        
        if attendance:
            attended += 1
        else:
            missed_sessions.append(sess)
    
    missed = total_sessions - attended
    percentage = (attended / total_sessions * 100) if total_sessions > 0 else 0
    
    return {
        'total_sessions': total_sessions,
        'attended': attended,
        'missed': missed,
        'percentage': round(percentage, 2),
        'missed_sessions': missed_sessions,
        'week_start': week_start,
        'week_end': week_end
    }

def generate_session_secret():
    """Generate a secure random session secret"""
    return secrets.token_urlsafe(32)
