from rest_framework import permissions

class IsUnitAuthorized(permissions.BasePermission):
    """
    Object-level permission ensuring users can only interact with records
    from units they are authorized to access.
    """
    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_superuser or user.role in ['ADMIN', 'MANAGER']:
            return True

        # Extract unit from object
        unit = getattr(obj, 'unit', None)
        if not unit and hasattr(obj, 'goods_receipt'):
            unit = getattr(obj.goods_receipt, 'unit', None)
        if not unit and hasattr(obj, 'invoice'):
            unit = getattr(obj.invoice, 'unit', None)

        if not unit:
            return True

        # Check UnitAccess or primary_unit
        if user.primary_unit == unit:
            return True

        return user.unit_accesses.filter(unit=unit).exists()

class CanApproveInvoice(permissions.BasePermission):
    """
    Permission ensuring the requesting user has the authority to approve invoices.
    """
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (user.is_superuser or user.role in ['ACCOUNTS', 'MANAGER', 'ADMIN'])
