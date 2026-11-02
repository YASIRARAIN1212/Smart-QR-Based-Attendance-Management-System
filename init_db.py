"""Initialize database with default admin user"""
from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    # Drop all tables and recreate
    print("Dropping existing tables...")
    db.drop_all()
    
    print("Creating new schema...")
    db.create_all()
    
    # Create default admin user
    print("Creating default admin user...")
    admin = User()  # type: ignore
    admin.email = 'admin@neduet.edu.pk'
    admin.full_name = 'System Administrator'
    admin.role = 'admin'
    admin.is_active = True
    admin.set_password('admin123')
    admin.force_password_reset = True
    
    db.session.add(admin)
    db.session.commit()
    
    print("\n" + "=" * 60)
    print("Database initialized successfully!")
    print("=" * 60)
    print("\nDefault Admin Credentials:")
    print("  Email: admin@neduet.edu.pk")
    print("  Password: admin123")
    print("\nAccess admin portal at: /auth/admin")
    print("IMPORTANT: Change the password on first login!")
    print("=" * 60)
