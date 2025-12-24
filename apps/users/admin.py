"""
Admin configuration for the users app.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import CommunityUser


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
        (_('Verification'), {'fields': ('email_verified',)}),
        (_('Important dates'), {'fields': ('last_login', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at', 'last_login')

