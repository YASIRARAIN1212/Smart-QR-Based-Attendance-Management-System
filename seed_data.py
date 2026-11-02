"""
Seed script to populate the database with demo data
Run this script to create demo accounts and test sessions
"""
# type: ignore

from app import create_app
from models import db, User, Subject, Session, FamilyEmail
from utils import generate_qr_token, save_qr_code
from datetime import datetime, timedelta
import pytz
import os

def seed_database(force=False):
    """
    Seed the database with demo data
    
    Args:
        force: If True, will delete existing data and re-seed
    """
    app = create_app()
    
    with app.app_context():
        # Check if data already exists
        existing_users = User.query.count()
        
        if existing_users > 0 and not force:
            print(f"Database already has {existing_users} users.")
            print("Run with force=True or delete attendance.db to re-seed.")
            print("Note: You can also create subjects/sessions via the teacher dashboard.")
            return
        
        if force:
            print("Force mode: Deleting existing data...")
            db.drop_all()
            db.create_all()
        
        print("Seeding database with demo data...")
        
        # Create Admin
        admin = User(  # type: ignore
            email='admin@campus.test',
            full_name='Admin User',
            role='admin',
            phone='555-0000'
        )
        admin.set_password('CampusDemo2026!')
        db.session.add(admin)
        
        # Create Employees (Faculty)
        teacher1 = User(  # type: ignore
            email='faculty01@campus.test',
            full_name='Prof. John Smith',
            role='employee',
            phone='555-0001'
        )
        teacher1.set_password('CampusDemo2026!')
        db.session.add(teacher1)
        
        teacher2 = User(  # type: ignore
            email='faculty01@campus.test',
            full_name='Dr. Sarah Johnson',
            role='employee',
            phone='555-0002'
        )
        teacher2.set_password('CampusDemo2026!')
        db.session.add(teacher2)
        
        # Create Students (Undergraduate)
        students = []
        for i in range(1, 11):
            student = User(  # type: ignore
                email=f'student001{i}@campus.test',
                full_name=f'Student {i} Name',
                role='undergraduate',
                student_id=f'STU{2025000 + i}',
                phone=f'555-{1000 + i}'
            )
            student.set_password('CampusDemo2026!')
            db.session.add(student)
            students.append(student)
        
        db.session.commit()
        print(f"Created 1 admin, 2 employees, and {len(students)} students")
        
        # Add family emails for first 3 students
        family_emails = [
            FamilyEmail(student_id=students[0].id, email='parent1@family.test', relationship='mother'),  # type: ignore
            FamilyEmail(student_id=students[0].id, email='parent1b@family.test', relationship='father'),  # type: ignore
            FamilyEmail(student_id=students[1].id, email='parent2@family.test', relationship='guardian'),  # type: ignore
            FamilyEmail(student_id=students[2].id, email='parent3@family.test', relationship='mother'),  # type: ignore
        ]
        for fe in family_emails:
            db.session.add(fe)
        
        db.session.commit()
        print(f"Added {len(family_emails)} family emails")
        
        # Create Subjects
        subjects = [
            Subject(name='Advanced Mathematics', code='MATH301', description='Calculus and Linear Algebra', teacher_id=teacher1.id),  # type: ignore
            Subject(name='Physics I', code='PHYS101', description='Classical Mechanics', teacher_id=teacher1.id),  # type: ignore
            Subject(name='Computer Science', code='CS201', description='Data Structures and Algorithms', teacher_id=teacher2.id),  # type: ignore
            Subject(name='Chemistry', code='CHEM101', description='General Chemistry', teacher_id=teacher2.id),  # type: ignore
        ]
        for subject in subjects:
            db.session.add(subject)
        
        db.session.commit()
        print(f"Created {len(subjects)} subjects")
        
        # Create Sessions (some past, some today, some upcoming)
        now = datetime.now(pytz.UTC)
        today_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
        
        # Default location (New York City - can be changed)
        default_lat = 40.7128
        default_lng = -74.0060
        
        sessions = []
        
        # Past sessions (yesterday)
        yesterday = today_start - timedelta(days=1)
        sessions.extend([
            Session(  # type: ignore
                subject_id=subjects[0].id,
                teacher_id=teacher1.id,
                location_lat=default_lat,
                location_lng=default_lng,
                location_name='Room 101, Main Building',
                start_time=yesterday,
                end_time=yesterday + timedelta(hours=1),
                notes='Introduction to Calculus',
                qr_token='temp1'
            ),
            Session(  # type: ignore
                subject_id=subjects[1].id,
                teacher_id=teacher1.id,
                location_lat=default_lat + 0.001,
                location_lng=default_lng + 0.001,
                location_name='Lab 203, Science Building',
                start_time=yesterday + timedelta(hours=2),
                end_time=yesterday + timedelta(hours=3),
                notes='Newton\'s Laws',
                qr_token='temp2'
            ),
        ])
        
        # Today's sessions
        sessions.extend([
            Session(  # type: ignore
                subject_id=subjects[2].id,
                teacher_id=teacher2.id,
                location_lat=default_lat,
                location_lng=default_lng,
                location_name='Computer Lab 1',
                start_time=today_start,
                end_time=today_start + timedelta(hours=2),
                notes='Binary Search Trees',
                qr_token='temp3'
            ),
            Session(  # type: ignore
                subject_id=subjects[0].id,
                teacher_id=teacher1.id,
                location_lat=default_lat + 0.0005,
                location_lng=default_lng - 0.0005,
                location_name='Room 105, Main Building',
                start_time=today_start + timedelta(hours=3),
                end_time=today_start + timedelta(hours=4),
                notes='Linear Algebra Basics',
                qr_token='temp4'
            ),
        ])
        
        # Upcoming sessions (tomorrow and next week)
        tomorrow = today_start + timedelta(days=1)
        next_week = today_start + timedelta(days=7)
        
        sessions.extend([
            Session(  # type: ignore
                subject_id=subjects[3].id,
                teacher_id=teacher2.id,
                location_lat=default_lat - 0.001,
                location_lng=default_lng + 0.001,
                location_name='Chemistry Lab',
                start_time=tomorrow + timedelta(hours=1),
                end_time=tomorrow + timedelta(hours=2),
                notes='Atomic Structure',
                qr_token='temp5'
            ),
            Session(  # type: ignore
                subject_id=subjects[1].id,
                teacher_id=teacher1.id,
                location_lat=default_lat,
                location_lng=default_lng,
                location_name='Lecture Hall A',
                start_time=next_week,
                end_time=next_week + timedelta(hours=1, minutes=30),
                notes='Energy and Momentum',
                qr_token='temp6'
            ),
        ])
        
        for sess in sessions:
            db.session.add(sess)
        
        db.session.flush()
        
        # Generate QR codes for all sessions
        qr_dir = 'static/qr_codes'
        os.makedirs(qr_dir, exist_ok=True)
        
        for sess in sessions:
            qr_token = generate_qr_token(sess.id, sess.start_time.isoformat())
            sess.qr_token = qr_token
            
            qr_filename = f'session_{sess.id}.png'
            qr_filepath = os.path.join(qr_dir, qr_filename)
            save_qr_code(qr_token, sess.id, qr_filepath)
        
        db.session.commit()
        print(f"Created {len(sessions)} sessions with QR codes")
        
        print("\n" + "="*60)
        print("DEMO ACCOUNTS CREATED:")
        print("="*60)
        print("\nAdmin Account:")
        print("  Email: admin@campus.test")
        print("  Password: CampusDemo2026!")
        print("\nEmployee (Faculty) Accounts:")
        print("  Email: faculty01@campus.test")
        print("  Password: CampusDemo2026!")
        print("\n  Email: faculty02@campus.test")
        print("  Password: CampusDemo2026!")
        print("\nStudent Accounts:")
        print("  Email: student001@campus.test to student010@campus.test")
        print("  Password: CampusDemo2026! (for all)")
        print("  Student IDs: STU2025001 to STU2025010")
        print("\nFamily Emails (for testing reports):")
        print("  parent1@family.test, parent1b@family.test (for student1)")
        print("  parent2@family.test (for student2)")
        print("  parent3@family.test (for student3)")
        print("="*60)
        print("\nIMPORTANT NOTES:")
        print("- Sessions created at default location (NYC coordinates)")
        print("- Update session locations via teacher dashboard if needed")
        print("- QR codes saved to static/qr_codes/")
        print("- Use student accounts to test QR scanning")
        print("- Configure SMTP settings in environment variables to enable emails")
        print("="*60)

if __name__ == '__main__':
    seed_database()
