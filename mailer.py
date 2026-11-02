from flask_mail import Message, Mail
from flask import current_app, render_template
from models import User, FamilyEmail
from utils import get_weekly_attendance_summary
import pytz
from datetime import datetime

mail = Mail()

def send_weekly_report(student_id):
    """
    Send weekly attendance report to student and family members
    """
    try:
        student = User.query.get(student_id)
        if not student or student.role not in ['undergraduate', 'postgraduate']:
            return False, "Invalid student"
        
        # Get weekly attendance summary
        summary = get_weekly_attendance_summary(student_id)
        
        # Prepare email recipients
        recipients = [student.email]
        family_emails = FamilyEmail.query.filter_by(student_id=student_id).all()
        recipients.extend([fe.email for fe in family_emails])
        
        # Prepare email data
        email_data = {
            'student_name': student.full_name,
            'student_id': student.student_id,
            'week_start': summary['week_start'].strftime('%B %d, %Y'),
            'week_end': summary['week_end'].strftime('%B %d, %Y'),
            'total_sessions': summary['total_sessions'],
            'attended': summary['attended'],
            'missed': summary['missed'],
            'percentage': summary['percentage'],
            'missed_sessions': summary['missed_sessions'],
            'year': datetime.now().year
        }
        
        # Determine recommendation based on attendance
        if summary['percentage'] >= 90:
            email_data['recommendation'] = "Excellent attendance! Keep up the great work."
        elif summary['percentage'] >= 75:
            email_data['recommendation'] = "Good attendance. Try to maintain consistency."
        elif summary['percentage'] >= 60:
            email_data['recommendation'] = "Attendance needs improvement. Please ensure regular attendance."
        else:
            email_data['recommendation'] = "Attendance is critically low. Please contact your advisor immediately."
        
        # Create email message
        msg = Message(
            subject=f"Weekly Attendance Report - {student.full_name}",
            recipients=recipients,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.system')
        )
        
        # Render HTML and text templates
        msg.html = render_template('email/weekly_report.html', **email_data)
        msg.body = render_template('email/weekly_report.txt', **email_data)
        
        # Send email
        mail.send(msg)
        
        return True, f"Report sent to {len(recipients)} recipient(s)"
    
    except Exception as e:
        return False, f"Error sending report: {str(e)}"

def send_test_email(recipient):
    """
    Send a test email to verify SMTP configuration
    """
    try:
        msg = Message(
            subject="Test Email - Smart Attendance System",
            recipients=[recipient],
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.system')
        )
        
        msg.body = "This is a test email from the Smart Attendance System. If you received this, your email configuration is working correctly!"
        msg.html = "<p>This is a test email from the <strong>Smart Attendance System</strong>.</p><p>If you received this, your email configuration is working correctly!</p>"
        
        mail.send(msg)
        return True, "Test email sent successfully"
    
    except Exception as e:
        return False, f"Error sending test email: {str(e)}"

def send_email(subject, recipients, html_body, text_body=None):
    """
    Generic email sending function for password resets, notifications, etc.
    """
    try:
        if isinstance(recipients, str):
            recipients = [recipients]
        
        msg = Message(
            subject=subject,
            recipients=recipients,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@attendance.system')
        )
        
        msg.html = html_body
        msg.body = text_body or html_body
        
        mail.send(msg)
        return True, "Email sent successfully"
    
    except Exception as e:
        return False, f"Error sending email: {str(e)}"
