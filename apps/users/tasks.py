"""
Celery tasks for the users app.

Example tasks for background processing.
"""
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()


@shared_task
def send_welcome_email(user_id):
    """
    Send a welcome email to a newly registered user.
    
    This is an example task that can be called after user registration.
    """
    try:
        user = User.objects.get(id=user_id)
        
        send_mail(
            subject='Welcome to AMDG!',
            message=f'Hello {user.get_display_name()},\n\nWelcome to AMDG Platform! We\'re excited to have you on board.\n\nBest regards,\nThe AMDG Team',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        return f'Welcome email sent to {user.email}'
    except User.DoesNotExist:
        return f'User with id {user_id} not found'
    except Exception as e:
        return f'Error sending email: {str(e)}'


@shared_task
def cleanup_old_sessions():
    """
    Clean up expired sessions from the database.
    
    This task can be scheduled to run periodically using Celery Beat.
    """
    from django.core.management import call_command
    call_command('clearsessions')
    return 'Old sessions cleaned up'


@shared_task
def send_email_verification(user_id, verification_url):
    """
    Send email verification link to user.
    
    Example task for email verification workflow.
    """
    try:
        user = User.objects.get(id=user_id)
        
        send_mail(
            subject='Verify your AMDG account',
            message=f'Hello {user.get_display_name()},\n\nPlease verify your email by clicking this link:\n{verification_url}\n\nBest regards,\nThe AMDG Team',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        return f'Verification email sent to {user.email}'
    except User.DoesNotExist:
        return f'User with id {user_id} not found'
    except Exception as e:
        return f'Error sending verification email: {str(e)}'


@shared_task
def send_password_reset_email(user_id, reset_url):
    """
    Send password reset link to user.
    
    Example task for password reset workflow.
    """
    try:
        user = User.objects.get(id=user_id)
        
        send_mail(
            subject='Reset your AMDG password',
            message=f'Hello {user.get_display_name()},\n\nYou requested to reset your password. Click this link to proceed:\n{reset_url}\n\nIf you didn\'t request this, please ignore this email.\n\nBest regards,\nThe AMDG Team',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        return f'Password reset email sent to {user.email}'
    except User.DoesNotExist:
        return f'User with id {user_id} not found'
    except Exception as e:
        return f'Error sending password reset email: {str(e)}'
