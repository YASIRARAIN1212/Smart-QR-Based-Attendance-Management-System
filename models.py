from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz

db = SQLAlchemy()

class User(db.Model):
    """User model supporting Employee, Undergraduate, Postgraduate, and Admin roles"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'employee', 'undergraduate', 'postgraduate', 'admin'
    full_name = db.Column(db.String(100), nullable=False)
    student_id = db.Column(db.String(50), unique=True, nullable=True, index=True)
    phone = db.Column(db.String(20), nullable=True)
    
    # Additional fields for students
    department = db.Column(db.String(100), nullable=True)
    year = db.Column(db.Integer, nullable=True)
    
    # Password management
    force_password_reset = db.Column(db.Boolean, default=False)
    last_password_change_at = db.Column(db.DateTime, nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    is_active = db.Column(db.Boolean, default=True)
    created_by_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # Password reset fields
    reset_token = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    family_emails = db.relationship('FamilyEmail', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    attendance_records = db.relationship('Attendance', backref='student', lazy='dynamic', cascade='all, delete-orphan')
    sessions_created = db.relationship('Session', backref='teacher', lazy='dynamic', foreign_keys='Session.teacher_id')
    
    def set_password(self, password):
        """Hash and set the user's password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Verify the user's password"""
        return check_password_hash(self.password_hash, password)
    
    def is_student(self):
        """Check if user is any type of student"""
        return self.role in ['undergraduate', 'postgraduate']
    
    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class FamilyEmail(db.Model):
    """Family email addresses for weekly reports"""
    __tablename__ = 'family_emails'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=False)
    relationship = db.Column(db.String(50), nullable=True)  # e.g., 'mother', 'father', 'guardian'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    
    def __repr__(self):
        return f'<FamilyEmail {self.email} for Student {self.student_id}>'


class Subject(db.Model):
    """Academic subjects (Math, Physics, etc.)"""
    __tablename__ = 'subjects'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    sessions = db.relationship('Session', backref='subject', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Subject {self.code}: {self.name}>'


class Session(db.Model):
    """Individual class sessions with location and QR code"""
    __tablename__ = 'sessions'
    
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False, index=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Location for verification
    location_lat = db.Column(db.Float, nullable=False)
    location_lng = db.Column(db.Float, nullable=False)
    location_name = db.Column(db.String(200), nullable=True)
    
    # Timing
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=False)
    
    # QR Code token (HMAC-secured)
    qr_token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    
    # Compensation session fields
    is_compensation = db.Column(db.Boolean, default=False, nullable=False)
    compensates_session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    attendance_records = db.relationship('Attendance', backref='session', lazy='dynamic', cascade='all, delete-orphan')
    compensated_session = db.relationship('Session', remote_side=[id], backref='compensation_sessions', foreign_keys=[compensates_session_id])
    
    def _ensure_utc(self, dt):
        """Convert datetime to UTC timezone-aware datetime"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=pytz.UTC)
        elif dt.tzinfo != pytz.UTC:
            return dt.astimezone(pytz.UTC)
        return dt
    
    def is_ongoing(self):
        """Check if session is currently ongoing"""
        now = datetime.now(pytz.UTC)
        start = self._ensure_utc(self.start_time)
        end = self._ensure_utc(self.end_time)
        return start <= now <= end
    
    def is_upcoming(self):
        """Check if session is in the future"""
        now = datetime.now(pytz.UTC)
        start = self._ensure_utc(self.start_time)
        return now < start
    
    def is_past(self):
        """Check if session has ended"""
        now = datetime.now(pytz.UTC)
        end = self._ensure_utc(self.end_time)
        return now > end
    
    def __repr__(self):
        subject_name = self.subject.name if self.subject else "Unknown"  # type: ignore
        return f'<Session {self.id} for {subject_name}>'


class Attendance(db.Model):
    """Attendance records with location verification"""
    __tablename__ = 'attendance'
    
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    
    # Location verification
    student_lat = db.Column(db.Float, nullable=False)
    student_lng = db.Column(db.Float, nullable=False)
    distance_meters = db.Column(db.Float, nullable=False)
    
    # Verification status
    verification_status = db.Column(db.String(50), nullable=False, index=True)
    # Possible values: 'VERIFIED', 'REJECTED_DISTANCE', 'REJECTED_DUPLICATE', 'REJECTED_OTHER', 'PENDING_DURATION'
    
    # Duration tracking
    check_in_time = db.Column(db.DateTime, nullable=True)
    check_out_time = db.Column(db.DateTime, nullable=True)
    duration_percentage = db.Column(db.Float, nullable=True)
    
    # Metadata
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC), index=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    # Unique constraint: one attendance record per student per session
    __table_args__ = (
        db.UniqueConstraint('student_id', 'session_id', name='unique_student_session'),
        db.Index('idx_student_date', 'student_id', 'timestamp'),
    )
    
    def __repr__(self):
        return f'<Attendance Student:{self.student_id} Session:{self.session_id} Status:{self.verification_status}>'


class AuditLog(db.Model):
    """Audit log for tracking system activities"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(50), nullable=True)
    entity_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC), index=True)
    
    def __repr__(self):
        return f'<AuditLog {self.action} at {self.timestamp}>'


class Enrollment(db.Model):
    """Official class roster: only enrolled students count toward subject attendance."""
    __tablename__ = 'enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False, index=True)
    enrolled_at = db.Column(db.DateTime, default=lambda: datetime.now(pytz.UTC))
    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', name='unique_student_subject'),)
    student = db.relationship('User', backref=db.backref('enrollments', lazy='dynamic'))
    subject = db.relationship('Subject', backref=db.backref('enrollments', lazy='dynamic'))