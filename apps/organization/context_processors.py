def user_roles(request):
    if not request.user.is_authenticated:
        return {'is_store': False, 'is_purchase': False, 'is_accounts': False, 'is_manager': False}
    user = request.user
    return {
        'is_store': user.is_store_staff,
        'is_purchase': user.is_purchase_staff,
        'is_accounts': user.is_accounts_staff,
        'is_manager': user.is_manager_or_admin,
        'current_role': user.role,
    }
