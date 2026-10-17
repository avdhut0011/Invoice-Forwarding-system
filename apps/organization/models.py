import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser

class RoleChoices(models.TextChoices):
    STORE = 'STORE', 'Store Staff'
    PURCHASE = 'PURCHASE', 'Purchase Staff'
    ACCOUNTS = 'ACCOUNTS', 'Accounts Staff'
    MANAGER = 'MANAGER', 'Management'
    ADMIN = 'ADMIN', 'System Administrator'

class LegalEntity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, unique=True)
    gstin = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

class Unit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    legal_entity = models.ForeignKey(LegalEntity, on_delete=models.CASCADE, related_name='units', null=True, blank=True)
    name = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=50, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class CostCenter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='cost_centers')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50)

    class Meta:
        unique_together = ('unit', 'code')

    def __str__(self):
        return f"{self.unit.name} - {self.name} ({self.code})"

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=RoleChoices.choices, default=RoleChoices.STORE)
    primary_unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True, related_name='primary_users')
    phone = models.CharField(max_length=30, blank=True, null=True)
    department = models.CharField(max_length=100, blank=True, null=True)
    is_department_admin = models.BooleanField(default=False, help_text="Grants user management rights within user's department.")

    def __str__(self):
        full_name = self.get_full_name()
        return full_name if full_name else self.username

    @property
    def is_superadmin(self):
        return self.is_superuser or self.role == RoleChoices.ADMIN

    @property
    def is_store_staff(self):
        return self.role == RoleChoices.STORE or self.is_superadmin

    @property
    def is_purchase_staff(self):
        return self.role == RoleChoices.PURCHASE or self.is_superadmin

    @property
    def is_accounts_staff(self):
        return self.role == RoleChoices.ACCOUNTS or self.is_superadmin

    @property
    def is_manager_or_admin(self):
        return self.role in [RoleChoices.MANAGER, RoleChoices.ADMIN] or self.is_superuser

    @property
    def is_store_admin(self):
        return self.is_superadmin or (self.role == RoleChoices.STORE and self.is_department_admin)

    @property
    def is_purchase_admin(self):
        return self.is_superadmin or (self.role == RoleChoices.PURCHASE and self.is_department_admin)

    @property
    def is_accounts_admin(self):
        return self.is_superadmin or (self.role == RoleChoices.ACCOUNTS and self.is_department_admin)

    @property
    def can_manage_users(self):
        return self.is_superadmin or self.is_department_admin

    @property
    def managed_department(self):
        if self.is_superadmin:
            return 'ALL'
        if self.is_department_admin:
            return self.role
        return None

class UnitAccess(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='unit_accesses')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='user_accesses')
    can_create = models.BooleanField(default=True)
    can_approve = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'unit')

class Delegation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delegator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='delegations_given')
    delegatee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='delegations_received')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
