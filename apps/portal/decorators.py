from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from apps.organization.models import RoleChoices

def get_home_url_for_user(user):
    """
    Returns the designated departmental landing route for a user.
    """
    if not user.is_authenticated:
        return 'portal:login'
    if user.is_superadmin or user.role == RoleChoices.MANAGER:
        return 'portal:dashboard'
    elif user.role == RoleChoices.STORE:
        return 'portal:store_portal'
    elif user.role == RoleChoices.PURCHASE:
        return 'portal:purchase_portal'
    elif user.role == RoleChoices.ACCOUNTS:
        return 'portal:accounts_portal'
    return 'portal:dashboard'

def store_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('portal:login')
        if not request.user.is_store_staff:
            messages.error(request, "Access Denied: You do not have permission to access the Store Department.")
            return redirect(get_home_url_for_user(request.user))
        return view_func(request, *args, **kwargs)
    return _wrapped

def purchase_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('portal:login')
        if not request.user.is_purchase_staff:
            messages.error(request, "Access Denied: You do not have permission to access the Purchase Department.")
            return redirect(get_home_url_for_user(request.user))
        return view_func(request, *args, **kwargs)
    return _wrapped

def accounts_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('portal:login')
        if not request.user.is_accounts_staff:
            messages.error(request, "Access Denied: You do not have permission to access the Accounts Department.")
            return redirect(get_home_url_for_user(request.user))
        return view_func(request, *args, **kwargs)
    return _wrapped

def executive_or_admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('portal:login')
        if not (request.user.is_superadmin or request.user.role == RoleChoices.MANAGER):
            # Regular departmental staff attempting to access executive overview gets routed to their department
            return redirect(get_home_url_for_user(request.user))
        return view_func(request, *args, **kwargs)
    return _wrapped

def user_management_access_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('portal:login')
        if not request.user.can_manage_users:
            messages.error(request, "Access Denied: You do not have user management permissions.")
            return redirect(get_home_url_for_user(request.user))
        return view_func(request, *args, **kwargs)
    return _wrapped
