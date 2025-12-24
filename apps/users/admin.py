"""
Admin configuration for the users app.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from .models import CommunityUser, Profile


@admin.register(CommunityUser)
class CommunityUserAdmin(BaseUserAdmin):
    """Admin configuration for CommunityUser model."""
    
    # The fields to be used in displaying the User model.
    list_display = ('email', 'username', 'first_name', 'last_name', 'is_staff', 'email_verified', 'oauth_provider')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'email_verified', 'oauth_provider')
    search_fields = ('email', 'username', 'first_name', 'last_name')
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('username', 'first_name', 'last_name')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('OAuth'), {'fields': ('oauth_provider', 'oauth_id')}),
        (_('Verification'), {'fields': ('email_verified', 'email_verified_at')}),
        (_('Important dates'), {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at', 'last_login', 'email_verified_at')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'preferred_name', 'contact_phone', 'preferred_language', 'timezone', 'created_at')
    list_filter = ('timezone', 'preferred_language', 'created_at')
    search_fields = ('user__email', 'user__username', 'preferred_name', 'contact_phone')
    readonly_fields = ('created_at', 'updated_at', 'profile_picture_uploaded_at')
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Profile Information', {
            'fields': ('preferred_name', 'contact_phone', 'preferred_language', 'timezone')
        }),
        ('Profile Picture', {
            'fields': ('profile_picture', 'profile_picture_uploaded_at')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def profile_picture_preview(self, obj):
        if obj.profile_picture:
            return format_html('<img src="{}" width="100" height="100" />', obj.profile_picture.url)
        return '-'
    profile_picture_preview.short_description = 'Profile Picture Preview'

