from functools import wraps
from flask import session, redirect, url_for, flash, request, jsonify
from models import User, AuditLog, db
from datetime import datetime
import pytz

def login_required(f):
    """Decorator to require login for a route"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.is_json or request.path.endswith('/mark'):
                return jsonify({'success': False, 'message': 'Please log in to access this resource'}), 401
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    """Decorator to require specific role(s) for a route"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                if request.is_json or request.path.endswith('/mark'):
                    return jsonify({'success': False, 'message': 'Please log in to access this resource'}), 401
                flash('Please log in to access this page.', 'warning')
                return redirect(url_for('login', next=request.url))
            
            user = User.query.get(session['user_id'])
            if not user or user.role not in roles:
                if request.is_json or request.path.endswith('/mark'):
                    return jsonify({'success': False, 'message': 'You do not have permission to access this resource'}), 403
                flash('You do not have permission to access this page.', 'danger')
                log_audit(
                    user_id=session.get('user_id'),
                    action='UNAUTHORIZED_ACCESS_ATTEMPT',
                    details=f'Attempted to access {request.path} with role {user.role if user else "unknown"}',
                    ip_address=request.remote_addr
                )
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def get_current_user():
    """Get the currently logged-in user"""
    if 'user_id' in session:
        return User.query.get(session['user_id'])
    return None

def log_audit(user_id=None, action='', entity_type=None, entity_id=None, details=None, ip_address=None):
    """Log an audit event"""
    try:
        audit_log = AuditLog(  # type: ignore
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip_address,
            timestamp=datetime.now(pytz.UTC)
        )
        db.session.add(audit_log)
        db.session.commit()
    except Exception as e:
        print(f"Error logging audit: {e}")
        db.session.rollback()