"""
Core functionality tests for Smart Attendance System
"""
# type: ignore

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import create_app
from models import db, User, Subject, Session, Attendance
from utils import calculate_distance, verify_location, generate_qr_token, validate_qr_token
from datetime import datetime, timedelta
import pytz

@pytest.fixture
def app():
    """Create test Flask app"""
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()

def test_distance_calculation():
    """Test GPS distance calculation"""
    # New York to New York (same location)
    lat1, lng1 = 40.7128, -74.0060
    lat2, lng2 = 40.7128, -74.0060
    distance = calculate_distance(lat1, lng1, lat2, lng2)
    assert distance < 1, "Same location should have ~0 distance"
    
    # New York to nearby location (~100m)
    lat2, lng2 = 40.7138, -74.0060
    distance = calculate_distance(lat1, lng1, lat2, lng2)
    assert 80 < distance < 120, f"Expected ~100m, got {distance}m"

def test_location_verification():
    """Test location verification with 100m radius"""
    session_lat, session_lng = 40.7128, -74.0060
    
    # Within range
    student_lat, student_lng = 40.7128, -74.0060
    is_valid, distance, msg = verify_location(session_lat, session_lng, student_lat, student_lng, 100)
    assert is_valid, "Same location should be valid"
    
    # Outside range
    student_lat, student_lng = 40.7200, -74.0060
    is_valid, distance, msg = verify_location(session_lat, session_lng, student_lat, student_lng, 100)
    assert not is_valid, "Far location should be invalid"
    assert distance is not None and distance > 100, f"Distance should be > 100m, got {distance}m"

def test_qr_token_generation_and_validation(app):
    """Test QR token generation and validation"""
    with app.app_context():
        session_id = 123
        
        # Generate token
        token = generate_qr_token(session_id)
        assert token is not None
        assert len(token) > 20
        
        # Validate token (should be valid)
        is_valid, msg = validate_qr_token(token, session_id, expiry_minutes=30)
        assert is_valid, f"Token should be valid: {msg}"
        
        # Validate with wrong session ID
        is_valid, msg = validate_qr_token(token, 999, expiry_minutes=30)
        assert not is_valid, "Token should be invalid for wrong session ID"

def test_user_password_hashing(app):
    """Test password hashing and verification"""
    with app.app_context():
        user = User(  # type: ignore
            email='test@example.com',
            full_name='Test User',
            role='undergraduate',
            student_id='TEST001'
        )
        
        password = 'SecurePassword123!'
        user.set_password(password)
        
        assert user.password_hash != password, "Password should be hashed"
        assert user.check_password(password), "Password verification should work"
        assert not user.check_password('WrongPassword'), "Wrong password should fail"

def test_duplicate_attendance_prevention(app):
    """Test that duplicate attendance is prevented"""
    with app.app_context():
        # Create test data
        teacher = User(email='employee@test.com', full_name='Teacher', role='employee')  # type: ignore
        teacher.set_password('test')
        db.session.add(teacher)
        
        student = User(email='student@test.com', full_name='Student', role='undergraduate', student_id='S001')  # type: ignore
        student.set_password('test')
        db.session.add(student)
        
        subject = Subject(name='Math', code='MATH101', teacher_id=1)  # type: ignore
        db.session.add(subject)
        
        session_obj = Session(  # type: ignore
            subject_id=1,
            teacher_id=1,
            location_lat=40.7128,
            location_lng=-74.0060,
            start_time=datetime.now(pytz.UTC),
            end_time=datetime.now(pytz.UTC) + timedelta(hours=1),
            qr_token='test_token'
        )
        db.session.add(session_obj)
        db.session.commit()
        
        # Create first attendance record
        attendance1 = Attendance(  # type: ignore
            student_id=student.id,
            session_id=session_obj.id,
            subject_id=subject.id,
            student_lat=40.7128,
            student_lng=-74.0060,
            distance_meters=0,
            verification_status='VERIFIED'
        )
        db.session.add(attendance1)
        db.session.commit()
        
        # Try to create duplicate
        attendance2 = Attendance(  # type: ignore
            student_id=student.id,
            session_id=session_obj.id,
            subject_id=subject.id,
            student_lat=40.7128,
            student_lng=-74.0060,
            distance_meters=0,
            verification_status='VERIFIED'
        )
        db.session.add(attendance2)
        
        with pytest.raises(Exception):
            db.session.commit()

def test_login_flow(client, app):
    """Test user login flow"""
    with app.app_context():
        # Create test user
        user = User(email='test@example.com', full_name='Test User', role='undergraduate', student_id='TEST001')  # type: ignore
        user.set_password('TestPassword123!')
        db.session.add(user)
        db.session.commit()
    
    # Test login
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'TestPassword123!'
    }, follow_redirects=True)
    
    assert response.status_code == 200
    
    # Test wrong password
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'WrongPassword'
    }, follow_redirects=True)
    
    assert b'Invalid' in response.data or b'invalid' in response.data

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
