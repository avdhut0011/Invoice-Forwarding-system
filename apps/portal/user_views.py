from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.exceptions import PermissionDenied

from apps.organization.models import User, Unit, RoleChoices, UnitAccess
from .decorators import user_management_access_required, get_home_url_for_user

@login_required
@user_management_access_required
def user_list_view(request):
    """
    Department-aware User Management Console.
    Superadmins can see and manage all users.
    Department Admins can only see and manage users of their own department.
    """
    user = request.user
    query = request.GET.get('q', '').strip()
    selected_dept = request.GET.get('dept', '').strip()

    # Determine allowed scope
    if user.is_superadmin:
        users_qs = User.objects.all().select_related('primary_unit')
        if selected_dept:
            users_qs = users_qs.filter(role=selected_dept)
    else:
        # Strictly scoped to department admin's department
        users_qs = User.objects.filter(role=user.role).select_related('primary_unit')
        selected_dept = user.role

    if query:
        users_qs = users_qs.filter(
            Q(username__icontains=query) |
            Q(first_name__icontains=query) |
            Q(last_name__icontains=query) |
            Q(email__icontains=query) |
            Q(phone__icontains=query)
        )

    users_list = users_qs.order_by('role', 'first_name', 'username')
    units = Unit.objects.filter(is_active=True).order_by('name')

    context = {
        'managed_users': users_list,
        'query': query,
        'selected_dept': selected_dept,
        'units': units,
        'role_choices': RoleChoices.choices,
        'is_superadmin': user.is_superadmin,
        'admin_department': user.managed_department,
    }
    return render(request, 'portal/users/user_list.html', context)

@login_required
@user_management_access_required
def user_create_view(request):
    """
    Create a new user.
    Superadmin can create users for any department and grant Department Admin rights.
    Department Admin can only create regular staff within their own department.
    """
    current_user = request.user
    units = Unit.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = request.POST.get('phone', '').strip()
        password = request.POST.get('password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        unit_id = request.POST.get('unit_id')

        # Determine role & admin flag based on actor permissions
        if current_user.is_superadmin:
            role = request.POST.get('role', RoleChoices.STORE)
            is_dept_admin = request.POST.get('is_department_admin') == '1'
        else:
            # Department Admin can only create users in their own department, cannot create admins
            role = current_user.role
            is_dept_admin = False

        # Validations
        if not username or not password:
            messages.error(request, "Username and password are required.")
            return redirect('portal:user_create')

        if password != confirm_password:
            messages.error(request, "Passwords do not match. Please re-enter.")
            return redirect('portal:user_create')

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return redirect('portal:user_create')

        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' is already taken.")
            return redirect('portal:user_create')

        primary_unit = Unit.objects.filter(id=unit_id).first() if unit_id else None

        new_user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            primary_unit=primary_unit,
            phone=phone,
            is_department_admin=is_dept_admin,
            is_staff=(role in [RoleChoices.ADMIN, RoleChoices.MANAGER] or is_dept_admin),
            is_superuser=(role == RoleChoices.ADMIN)
        )

        if primary_unit:
            UnitAccess.objects.get_or_create(user=new_user, unit=primary_unit, defaults={'can_create': True, 'can_approve': True})

        role_label = dict(RoleChoices.choices).get(role, role)
        admin_tag = " (Department Admin)" if is_dept_admin else ""
        messages.success(request, f"User '{new_user.username}' successfully created for {role_label}{admin_tag}!")
        return redirect('portal:user_list')

    context = {
        'units': units,
        'role_choices': RoleChoices.choices,
        'is_superadmin': current_user.is_superadmin,
        'current_user_dept': current_user.role,
    }
    return render(request, 'portal/users/user_form.html', context)

@login_required
@user_management_access_required
def user_update_password_view(request, user_id):
    """
    Update or reset password for a user.
    Department Admins can only reset passwords for staff in their own department.
    Superadmins can reset passwords for anyone.
    """
    current_user = request.user
    target_user = get_object_or_404(User, id=user_id)

    # Permission check: Department Admins cannot update other departments or superadmins
    if not current_user.is_superadmin:
        if target_user.role != current_user.role or target_user.is_superadmin:
            messages.error(request, "Access Denied: You cannot modify credentials for this user.")
            return redirect('portal:user_list')

    if request.method == 'POST':
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        if not new_password or len(new_password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return redirect('portal:user_list')

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('portal:user_list')

        target_user.set_password(new_password)
        target_user.save()
        messages.success(request, f"Password for user '{target_user.username}' has been successfully updated!")
        return redirect('portal:user_list')

    return redirect('portal:user_list')

@login_required
@user_management_access_required
def user_toggle_status_view(request, user_id):
    """
    Activate or deactivate user account.
    """
    current_user = request.user
    target_user = get_object_or_404(User, id=user_id)

    if target_user == current_user:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('portal:user_list')

    if not current_user.is_superadmin:
        if target_user.role != current_user.role or target_user.is_superadmin:
            messages.error(request, "Access Denied: You cannot modify this user.")
            return redirect('portal:user_list')

    target_user.is_active = not target_user.is_active
    target_user.save()
    status_label = "activated" if target_user.is_active else "deactivated"
    messages.info(request, f"User '{target_user.username}' has been {status_label}.")
    return redirect('portal:user_list')
