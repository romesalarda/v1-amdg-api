"""
Helper functions for staff invite management and permission templates.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.events.models import (
    Event, EventStaff, EventPermission, EventPermissionAssignment,
    EventPermissionCategoryChoices
)
from apps.events.services.permission_templates import get_template, is_valid_template
from apps.organisations.models import UserOrganisationMembership


def apply_permission_template(event, user, template_code, assigned_by=None):
    """
    Apply a permission template to a user for an event.
    
    Creates EventPermission entries if they don't exist and assigns them to the user
    with the CRUD settings defined in the template.
    
    Args:
        event (Event): The event to apply permissions for
        user (User): The user to assign permissions to
        template_code (str): The code of the permission template to apply
        assigned_by (User, optional): The user who is assigning these permissions
    
    Returns:
        list: List of EventPermissionAssignment objects created
    
    Raises:
        ValidationError: If the template code is invalid
    """
    if not is_valid_template(template_code):
        raise ValidationError(f"Invalid permission template code: {template_code}")
    
    template = get_template(template_code)
    assignments = []
    
    with transaction.atomic():
        for perm_config in template['permissions']:
            # Get or create the permission
            permission, created = EventPermission.objects.get_or_create(
                code=perm_config['code'],
                defaults={
                    'name': perm_config['code'].replace('_', ' ').title(),
                    'description': f"Permission for {perm_config['code']}",
                    'category': perm_config['category']
                }
            )
            
            # Check if assignment already exists
            existing = EventPermissionAssignment.objects.filter(
                event=event,
                user=user,
                permission=permission
            ).first()
            
            if existing:
                # Update existing assignment
                crud = perm_config['crud']
                existing.read_only = crud.get('read_only', False)
                existing.allow_create = crud.get('allow_create', False)
                existing.allow_update = crud.get('allow_update', False)
                existing.allow_delete = crud.get('allow_delete', False)
                existing.assigned_by = assigned_by
                existing.save()
                assignments.append(existing)
            else:
                # Create new assignment
                crud = perm_config['crud']
                assignment = EventPermissionAssignment.objects.create(
                    event=event,
                    user=user,
                    permission=permission,
                    read_only=crud.get('read_only', False),
                    allow_create=crud.get('allow_create', False),
                    allow_update=crud.get('allow_update', False),
                    allow_delete=crud.get('allow_delete', False),
                    assigned_by=assigned_by
                )
                assignments.append(assignment)
    
    return assignments


def validate_user_in_organization(user, event):
    """
    Validate that a user is a member of the event's organization.
    
    Args:
        user (User): The user to validate
        event (Event): The event whose organization to check
    
    Returns:
        bool: True if user is a member, False otherwise
    
    Raises:
        ValidationError: If event has no organization or user is not a member
    """
    if not event.organisation:
        # Events without an organization don't require membership
        return True
    
    is_member = UserOrganisationMembership.objects.filter(
        organisation=event.organisation,
        user=user
    ).exists()
    
    if not is_member:
        raise ValidationError(
            f"User {user.email} is not a member of the organization {event.organisation.title}. "
            "Only organization members can be invited as event staff."
        )
    
    return True


def get_eligible_staff_for_event(event):
    """
    Get all users eligible to be invited as staff for an event.
    
    Returns organization members who are not already staff or have pending invites.
    
    Args:
        event (Event): The event to get eligible staff for
    
    Returns:
        QuerySet: QuerySet of User objects eligible to be invited
    """
    from django.contrib.auth import get_user_model
    from apps.events.models import EventStaffInvite
    
    User = get_user_model()
    
    if not event.organisation:
        # No organization = no restriction, return empty set for safety
        # or return all users if that's the desired behavior
        return User.objects.none()
    
    # Get organization members
    org_member_ids = UserOrganisationMembership.objects.filter(
        organisation=event.organisation
    ).values_list('user_id', flat=True)
    
    # Get users who are already staff
    existing_staff_ids = EventStaff.objects.filter(
        event=event
    ).values_list('user_id', flat=True)
    
    # Get users who have pending invites
    pending_invite_ids = EventStaffInvite.objects.filter(
        event=event,
        is_active=True,
        accepted=False
    ).values_list('target_user_id', flat=True)
    
    # Return org members who are not already staff and don't have pending invites
    eligible_users = User.objects.filter(
        id__in=org_member_ids
    ).exclude(
        id__in=existing_staff_ids
    ).exclude(
        id__in=pending_invite_ids
    ).order_by('first_name', 'last_name', 'email')
    
    return eligible_users


def bulk_create_invites(event, user_ids, invited_by, permission_template=None, expires_at=None):
    """
    Create multiple staff invites at once.
    
    Args:
        event (Event): The event to create invites for
        user_ids (list): List of user IDs to invite
        invited_by (User): The user creating the invites
        permission_template (str, optional): Permission template code to apply
        expires_at (datetime, optional): Expiration date for invites
    
    Returns:
        dict: Dictionary with 'created' (list of invites) and 'errors' (list of error dicts)
    """
    from django.contrib.auth import get_user_model
    from apps.events.models import EventStaffInvite, EventStaff
    from django.utils import timezone
    
    User = get_user_model()
    
    created = []
    errors = []
    
    # Validate permission template if provided
    if permission_template and not is_valid_template(permission_template):
        return {
            'created': [],
            'errors': [{'error': f'Invalid permission template: {permission_template}'}]
        }
    
    # Validate expiry date
    if expires_at and expires_at < timezone.now():
        return {
            'created': [],
            'errors': [{'error': 'Expiry date must be in the future'}]
        }
    
    for user_id in user_ids:
        try:
            user = User.objects.get(id=user_id)
            
            # Validate user is in organization
            try:
                validate_user_in_organization(user, event)
            except ValidationError as e:
                errors.append({
                    'user_id': user_id,
                    'email': user.email,
                    'error': str(e)
                })
                continue
            
            # Check if user already has an active invite
            existing_invite = EventStaffInvite.objects.filter(
                event=event,
                target_user=user,
                is_active=True
            ).first()
            
            if existing_invite:
                errors.append({
                    'user_id': user_id,
                    'email': user.email,
                    'error': 'User already has an active invite for this event'
                })
                continue
            
            # Check if user is already staff
            existing_staff = EventStaff.objects.filter(
                event=event,
                user=user
            ).first()
            
            if existing_staff:
                errors.append({
                    'user_id': user_id,
                    'email': user.email,
                    'error': 'User is already a staff member for this event'
                })
                continue
            
            # Create the invite
            invite = EventStaffInvite.objects.create(
                event=event,
                target_user=user,
                invited_by=invited_by,
                permission_template=permission_template,
                expires_at=expires_at,
                is_active=True
            )
            created.append(invite)
            
        except User.DoesNotExist:
            errors.append({
                'user_id': user_id,
                'error': 'User not found'
            })
        except Exception as e:
            errors.append({
                'user_id': user_id,
                'error': str(e)
            })
    
    return {
        'created': created,
        'errors': errors
    }
