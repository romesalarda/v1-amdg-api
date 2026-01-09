"""
Production-grade admin configuration for the users app.

This module provides comprehensive Django admin interfaces for user and profile management
with advanced features including inlines, custom actions, filters, and enhanced displays.

Features:
    - Custom user admin with OAuth information
    - Inline profile editing
    - Advanced search and filtering
    - Custom actions (bulk operations)
    - Enhanced list displays with computed fields
    - Read-only sensitive fields
    - Profile picture preview

Author: AMDG Platform Team
Version: 1.0.0
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.contrib.admin import SimpleListFilter
from .models import CommunityUser, Profile


class EmailVerifiedFilter(SimpleListFilter):
    """
    Custom filter for email verification status.
    
    Provides filtering options:
        - Verified: Users with verified emails
        - Unverified: Users with unverified emails
    """
    title = _('Email Verification Status')
    parameter_name = 'email_verification'
    
    def lookups(self, request, model_admin):
        """Define filter options."""
        return (
            ('verified', _('Verified')),
            ('unverified', _('Unverified')),
        )
    
    def queryset(self, request, queryset):
        """Filter queryset based on selection."""
        if self.value() == 'verified':
            return queryset.filter(email_verified=True)
        if self.value() == 'unverified':
            return queryset.filter(email_verified=False)
        return queryset


class HasProfileFilter(SimpleListFilter):
    """
    Custom filter for users with/without profiles.
    
    Provides filtering options:
        - Has Profile: Users with complete profiles
        - No Profile: Users without profiles
    """
    title = _('Profile Status')
    parameter_name = 'profile_status'
    
    def lookups(self, request, model_admin):
        """Define filter options."""
        return (
            ('has_profile', _('Has Profile')),
            ('no_profile', _('No Profile')),
        )
    
    def queryset(self, request, queryset):
        """Filter queryset based on selection."""
        if self.value() == 'has_profile':
            return queryset.filter(profile__isnull=False)
        if self.value() == 'no_profile':
            return queryset.filter(profile__isnull=True)
        return queryset


class ProfileInline(admin.StackedInline):
    """
    Inline admin for Profile model.
    
    Allows editing user profile directly from user admin page.
    Displays profile information in a stacked format for better UX.
    """
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile Information'
    
    fieldsets = (
        (_('Display Information'), {
            'fields': ('preferred_name', 'profile_picture', 'profile_picture_preview'),
            'classes': ('wide',)
        }),
        (_('Contact & Location'), {
            'fields': ('contact_phone', 'area_from'),
            'classes': ('wide',)
        }),
        (_('Preferences'), {
            'fields': ('preferred_language', 'timezone'),
            'classes': ('wide',)
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at', 'profile_picture_uploaded_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at', 'profile_picture_uploaded_at', 'profile_picture_preview')
    
    def profile_picture_preview(self, obj):
        """Display profile picture preview in admin."""
        if obj and obj.profile_picture:
            return format_html(
                '<img src="{}" style="max-width: 150px; max-height: 150px; border-radius: 8px;" />',
                obj.profile_picture.url
            )
        return format_html('<span style="color: #999;">No picture uploaded</span>')
    
    profile_picture_preview.short_description = _('Current Profile Picture')


@admin.register(CommunityUser)
class CommunityUserAdmin(BaseUserAdmin):
    """
    Production-grade admin configuration for CommunityUser model.
    
    Features:
        - Inline profile editing
        - Advanced search across multiple fields
        - Custom filters (email verified, OAuth provider, profile status)
        - Enhanced list display with computed fields
        - Custom actions (bulk email verification, OAuth reset)
        - Read-only fields for security
        - Organized fieldsets
        - Profile link in list view
    
    Custom Actions:
        - Verify emails (bulk)
        - Reset OAuth information (bulk)
        - Deactivate users (bulk)
        - Activate users (bulk)
    """
    
    inlines = [ProfileInline]
    
    # List view configuration
    list_display = (
        'email',
        'display_name_field',
        'full_name',
        'is_staff',
        'is_active',
        'email_status',
        'oauth_badge',
        'profile_link',
        'date_joined_formatted',
    )
    list_filter = (
        'is_staff',
        'is_superuser',
        'is_active',
        EmailVerifiedFilter,
        'oauth_provider',
        HasProfileFilter,
        'date_joined',
        'groups',
    )
    search_fields = (
        'email',
        'username',
        'first_name',
        'last_name',
        'oauth_id',
        'profile__preferred_name',
        'profile__contact_phone',
    )
    ordering = ('-created_at',)
    list_per_page = 25
    list_select_related = ('profile',)
    
    # Detail view configuration
    fieldsets = (
        (None, {
            'fields': ('email', 'password')
        }),
        (_('Personal Information'), {
            'fields': ('username', 'first_name', 'last_name'),
            'classes': ('wide',)
        }),
        (_('Permissions'), {
            'fields': (
                'is_active',
                'is_staff',
                'is_superuser',
                'groups',
                'user_permissions'
            ),
            'classes': ('collapse',)
        }),
        (_('OAuth Authentication'), {
            'fields': ('oauth_provider', 'oauth_id'),
            'classes': ('collapse',)
        }),
        (_('Email Verification'), {
            'fields': ('email_verified', 'email_verified_at'),
            'classes': ('collapse',)
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'email',
                'username',
                'password1',
                'password2',
                'first_name',
                'last_name'
            ),
        }),
    )
    
    readonly_fields = (
        'created_at',
        'updated_at',
        'last_login',
        'email_verified_at',
        'date_joined'
    )
    
    # Custom display methods
    @admin.display(description='Display Name', ordering='username')
    def display_name_field(self, obj):
        """Display user's preferred display name."""
        return obj.get_display_name()
    
    @admin.display(description='Full Name', ordering='first_name')
    def full_name(self, obj):
        """Display user's full name or placeholder."""
        full_name = obj.get_full_name()
        if full_name:
            return full_name
        return format_html('<span style="color: #999;">Not provided</span>')
    
    @admin.display(description='Email Status')
    def email_status(self, obj):
        """Display email verification status with visual indicator."""
        if obj.email_verified:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">✓ Verified</span>'
            )
        return format_html(
            '<span style="color: #dc3545; font-weight: bold;">✗ Unverified</span>'
        )
    
    @admin.display(description='OAuth', ordering='oauth_provider')
    def oauth_badge(self, obj):
        """Display OAuth provider with colored badge."""
        if obj.oauth_provider:
            colors = {
                'google': '#4285F4',
                'github': '#333333',
            }
            color = colors.get(obj.oauth_provider, '#6c757d')
            return format_html(
                '<span style="background-color: {}; color: white; padding: 2px 8px; '
                'border-radius: 3px; font-size: 11px; font-weight: bold;">{}</span>',
                color,
                obj.oauth_provider.upper()
            )
        return format_html('<span style="color: #999;">—</span>')
    
    @admin.display(description='Profile')
    def profile_link(self, obj):
        """Display link to user's profile."""
        if hasattr(obj, 'profile') and obj.profile:
            url = reverse('admin:users_profile_change', args=[obj.profile.pk])
            return format_html(
                '<a href="{}" style="color: #0066cc;">View Profile →</a>',
                url
            )
        return format_html('<span style="color: #999;">No profile</span>')
    
    @admin.display(description='Joined', ordering='date_joined')
    def date_joined_formatted(self, obj):
        """Display formatted join date."""
        if obj.date_joined:
            return obj.date_joined.strftime('%Y-%m-%d %H:%M')
        return '—'
    
    # Custom admin actions
    @admin.action(description='✓ Verify selected emails')
    def verify_emails(self, request, queryset):
        """Bulk verify user emails."""
        from django.utils import timezone
        updated = queryset.filter(email_verified=False).update(
            email_verified=True,
            email_verified_at=timezone.now()
        )
        self.message_user(
            request,
            f'{updated} user email(s) have been verified.'
        )
    
    @admin.action(description='✗ Reset OAuth information')
    def reset_oauth(self, request, queryset):
        """Bulk reset OAuth information."""
        updated = queryset.exclude(oauth_provider='').update(
            oauth_provider='',
            oauth_id=''
        )
        self.message_user(
            request,
            f'OAuth information reset for {updated} user(s).'
        )
    
    @admin.action(description='⚠ Deactivate selected users')
    def deactivate_users(self, request, queryset):
        """Bulk deactivate users."""
        updated = queryset.filter(is_active=True).update(is_active=False)
        self.message_user(
            request,
            f'{updated} user(s) have been deactivated.',
            level='WARNING'
        )
    
    @admin.action(description='✓ Activate selected users')
    def activate_users(self, request, queryset):
        """Bulk activate users."""
        updated = queryset.filter(is_active=False).update(is_active=True)
        self.message_user(
            request,
            f'{updated} user(s) have been activated.'
        )
    
    actions = [
        'verify_emails',
        'reset_oauth',
        'deactivate_users',
        'activate_users',
    ]
    
    def get_queryset(self, request):
        """
        Optimize queryset with select_related.
        
        Reduces database queries by prefetching related objects.
        """
        queryset = super().get_queryset(request)
        return queryset.select_related('profile')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """
    Production-grade admin configuration for Profile model.
    
    Features:
        - Enhanced list display with user information
        - Advanced search across user and profile fields
        - Custom filters (timezone, language, location)
        - Profile picture preview
        - User link in list view
        - Organized fieldsets
        - Read-only sensitive fields
    
    Custom Actions:
        - Clear profile pictures (bulk)
    """
    
    list_display = (
        'user_link',
        'preferred_name_display',
        'contact_phone_display',
        'area_display',
        'preferred_language',
        'timezone',
        'profile_picture_status',
        'created_at_formatted',
    )
    list_filter = (
        'timezone',
        'preferred_language',
        'area_from',
        'created_at',
    )
    search_fields = (
        'user__email',
        'user__username',
        'user__first_name',
        'user__last_name',
        'preferred_name',
        'contact_phone',
    )
    readonly_fields = (
        'created_at',
        'updated_at',
        'profile_picture_uploaded_at',
        'profile_picture_preview',
        'user_details'
    )
    list_per_page = 25
    list_select_related = ('user', 'area_from')
    
    fieldsets = (
        (_('User'), {
            'fields': ('user', 'user_details')
        }),
        (_('Profile Information'), {
            'fields': ('preferred_name', 'contact_phone'),
            'classes': ('wide',)
        }),
        (_('Location'), {
            'fields': ('area_from',),
            'classes': ('wide',)
        }),
        (_('Preferences'), {
            'fields': ('preferred_language', 'timezone'),
            'classes': ('wide',)
        }),
        (_('Profile Picture'), {
            'fields': ('profile_picture', 'profile_picture_preview', 'profile_picture_uploaded_at'),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # Custom display methods
    @admin.display(description='User', ordering='user__email')
    def user_link(self, obj):
        """Display link to user admin page."""
        url = reverse('admin:users_communityuser_change', args=[obj.user.pk])
        return format_html(
            '<a href="{}" style="color: #0066cc; font-weight: 500;">{}</a>',
            url,
            obj.user.email
        )
    
    @admin.display(description='Preferred Name')
    def preferred_name_display(self, obj):
        """Display preferred name or placeholder."""
        if obj.preferred_name:
            return obj.preferred_name
        return format_html('<span style="color: #999;">Not set</span>')
    
    @admin.display(description='Phone')
    def contact_phone_display(self, obj):
        """Display contact phone or placeholder."""
        if obj.contact_phone:
            return obj.contact_phone
        return format_html('<span style="color: #999;">Not provided</span>')
    
    @admin.display(description='Area')
    def area_display(self, obj):
        """Display area location or placeholder."""
        if obj.area_from:
            return obj.area_from.name if hasattr(obj.area_from, 'name') else str(obj.area_from)
        return format_html('<span style="color: #999;">Not set</span>')
    
    @admin.display(description='Picture')
    def profile_picture_status(self, obj):
        """Display profile picture status."""
        if obj.profile_picture:
            return format_html(
                '<span style="color: #28a745;">✓ Uploaded</span>'
            )
        return format_html('<span style="color: #999;">No picture</span>')
    
    @admin.display(description='Created', ordering='created_at')
    def created_at_formatted(self, obj):
        """Display formatted creation date."""
        if obj.created_at:
            return obj.created_at.strftime('%Y-%m-%d %H:%M')
        return '—'
    
    @admin.display(description='Profile Picture Preview')
    def profile_picture_preview(self, obj):
        """Display large profile picture preview."""
        if obj.profile_picture:
            return format_html(
                '<img src="{}" style="max-width: 300px; max-height: 300px; '
                'border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);" />',
                obj.profile_picture.url
            )
        return format_html(
            '<div style="padding: 20px; background: #f8f9fa; border-radius: 8px; '
            'text-align: center; color: #999;">No profile picture uploaded</div>'
        )
    
    @admin.display(description='User Information')
    def user_details(self, obj):
        """Display comprehensive user information."""
        user = obj.user
        info_html = f'''
        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 10px 0;">
            <div style="margin-bottom: 8px;">
                <strong>Email:</strong> {user.email}
            </div>
            <div style="margin-bottom: 8px;">
                <strong>Username:</strong> {user.username or '<span style="color: #999;">Not set</span>'}
            </div>
            <div style="margin-bottom: 8px;">
                <strong>Full Name:</strong> {user.get_full_name() or '<span style="color: #999;">Not set</span>'}
            </div>
            <div style="margin-bottom: 8px;">
                <strong>Status:</strong> 
                {'<span style="color: #28a745;">Active</span>' if user.is_active else '<span style="color: #dc3545;">Inactive</span>'}
            </div>
            <div style="margin-bottom: 8px;">
                <strong>Email Verified:</strong> 
                {'<span style="color: #28a745;">Yes</span>' if user.email_verified else '<span style="color: #dc3545;">No</span>'}
            </div>
            <div>
                <strong>Joined:</strong> {user.date_joined.strftime('%Y-%m-%d %H:%M') if user.date_joined else 'N/A'}
            </div>
        </div>
        '''
        return mark_safe(info_html)
    
    # Custom admin actions
    @admin.action(description='✗ Clear profile pictures')
    def clear_profile_pictures(self, request, queryset):
        """Bulk clear profile pictures."""
        updated = 0
        for profile in queryset:
            if profile.profile_picture:
                profile.profile_picture.delete()
                profile.save()
                updated += 1
        
        self.message_user(
            request,
            f'Profile pictures cleared for {updated} profile(s).'
        )
    
    actions = ['clear_profile_pictures']
    
    def get_queryset(self, request):
        """
        Optimize queryset with select_related.
        
        Reduces database queries by prefetching related objects.
        """
        queryset = super().get_queryset(request)
        return queryset.select_related('user', 'area_from')

