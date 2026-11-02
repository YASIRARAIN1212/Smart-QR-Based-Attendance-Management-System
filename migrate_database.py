"""
Database migration script to update schema and migrate data for NED University Portal
Run this script once to migrate from old schema to new schema
"""

from app import create_app
from models import db, User
from datetime import datetime
import pytz

def migrate_database():
    """Migrate database schema and data"""
    app = create_app()
    
    with app.app_context():
        print("Starting database migration...")
        
        # Step 1: Add new columns if they don't exist (SQLAlchemy will handle this with create_all)
        print("Step 1: Creating new schema...")
        db.create_all()
        print("Schema updated.")
        
        # Step 2: Migrate existing data
        print("\nStep 2: Migrating existing user roles...")
        
        # Get all users
        users = User.query.all()
        
        student_count = 0
        teacher_count = 0
        admin_count = 0
        
        for user in users:
            updated = False
            
            # Migrate 'student' to 'undergraduate'
            if user.role == 'student':
                user.role = 'undergraduate'
                if not user.department:
                    user.department = 'General'
                if not user.year:
                    user.year = 1
                student_count += 1
                updated = True
            
            # Migrate 'teacher' to 'employee'
            elif user.role == 'teacher':
                user.role = 'employee'
                if not user.department:
                    user.department = 'Faculty'
                teacher_count += 1
                updated = True
            
            # Keep admin as is
            elif user.role == 'admin':
                admin_count += 1
            
            # Set force_password_reset to False for existing users
            if user.force_password_reset is None:
                user.force_password_reset = False
                updated = True
            
            if updated:
                print(f"  - Migrated user: {user.email} (role: {user.role})")
        
        # Commit all changes
        db.session.commit()
        
        print(f"\nMigration Summary:")
        print(f"  - Students migrated to Undergraduate: {student_count}")
        print(f"  - Teachers migrated to Employee: {teacher_count}")
        print(f"  - Admins: {admin_count}")
        print(f"  - Total users: {len(users)}")
        
        print("\nDatabase migration completed successfully!")
        print("\nNew Roles:")
        print("  - admin: Administrative access")
        print("  - employee: Faculty/Staff (previously 'teacher')")
        print("  - undergraduate: Undergraduate students (previously 'student')")
        print("  - postgraduate: Postgraduate students (new)")

if __name__ == '__main__':
    migrate_database()
