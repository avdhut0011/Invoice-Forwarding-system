from django.test import TestCase, Client
from django.urls import reverse
from apps.organization.models import LegalEntity, Unit, User, RoleChoices

class PortalViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.legal_entity = LegalEntity.objects.create(name="Ashoka Education Foundation", code="AEF")
        self.unit = Unit.objects.create(name="Ashoka Universal School - Ashoka Marg", code="AUS-AM", legal_entity=self.legal_entity)
        
        # Superadmin
        self.admin_user = User.objects.create_user(
            username="admin_user",
            password="password123",
            role=RoleChoices.ADMIN,
            primary_unit=self.unit,
            email="admin@test.com",
            is_superuser=True
        )

        # Store Staff & Store Admin
        self.store_user = User.objects.create_user(
            username="store_staff",
            password="password123",
            role=RoleChoices.STORE,
            primary_unit=self.unit,
            email="store@test.com"
        )
        self.store_admin = User.objects.create_user(
            username="store_admin",
            password="password123",
            role=RoleChoices.STORE,
            is_department_admin=True,
            primary_unit=self.unit,
            email="store.admin@test.com"
        )

        # Purchase Staff
        self.purchase_user = User.objects.create_user(
            username="purchase_staff",
            password="password123",
            role=RoleChoices.PURCHASE,
            primary_unit=self.unit,
            email="purchase@test.com"
        )

        # Accounts Staff
        self.accounts_user = User.objects.create_user(
            username="accounts_staff",
            password="password123",
            role=RoleChoices.ACCOUNTS,
            primary_unit=self.unit,
            email="accounts@test.com"
        )

    def test_unauthenticated_redirect(self):
        response = self.client.get(reverse('portal:dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_login_view(self):
        response = self.client.get(reverse('portal:login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_departmental_access_segregation(self):
        # 1. Store Staff: can access Store, blocked from Purchase and Accounts
        self.client.login(username="store_staff", password="password123")
        self.assertEqual(self.client.get(reverse('portal:store_portal')).status_code, 200)
        
        resp_purch = self.client.get(reverse('portal:purchase_portal'))
        self.assertEqual(resp_purch.status_code, 302)
        self.assertIn('/store/', resp_purch.url)

        resp_accts = self.client.get(reverse('portal:accounts_portal'))
        self.assertEqual(resp_accts.status_code, 302)
        self.assertIn('/store/', resp_accts.url)

        # 2. Purchase Staff: can access Purchase, blocked from Store and Accounts
        self.client.login(username="purchase_staff", password="password123")
        self.assertEqual(self.client.get(reverse('portal:purchase_portal')).status_code, 200)

        resp_store = self.client.get(reverse('portal:store_portal'))
        self.assertEqual(resp_store.status_code, 302)
        self.assertIn('/purchase/', resp_store.url)

        resp_accts = self.client.get(reverse('portal:accounts_portal'))
        self.assertEqual(resp_accts.status_code, 302)
        self.assertIn('/purchase/', resp_accts.url)

        # 3. Accounts Staff: can access Accounts, blocked from Store and Purchase
        self.client.login(username="accounts_staff", password="password123")
        self.assertEqual(self.client.get(reverse('portal:accounts_portal')).status_code, 200)

        resp_store = self.client.get(reverse('portal:store_portal'))
        self.assertEqual(resp_store.status_code, 302)
        self.assertIn('/accounts/', resp_store.url)

        resp_purch = self.client.get(reverse('portal:purchase_portal'))
        self.assertEqual(resp_purch.status_code, 302)
        self.assertIn('/accounts/', resp_purch.url)

        # 4. Superadmin: can access all portals
        self.client.login(username="admin_user", password="password123")
        self.assertEqual(self.client.get(reverse('portal:store_portal')).status_code, 200)
        self.assertEqual(self.client.get(reverse('portal:purchase_portal')).status_code, 200)
        self.assertEqual(self.client.get(reverse('portal:accounts_portal')).status_code, 200)
        self.assertEqual(self.client.get(reverse('portal:dashboard')).status_code, 200)

    def test_department_admin_user_management(self):
        # Regular staff cannot access user management
        self.client.login(username="store_staff", password="password123")
        resp = self.client.get(reverse('portal:user_list'))
        self.assertEqual(resp.status_code, 302)

        # Store Admin can access user management
        self.client.login(username="store_admin", password="password123")
        resp = self.client.get(reverse('portal:user_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'portal/users/user_list.html')
        # Store admin only sees Store staff
        self.assertIn('store_staff', [u.username for u in resp.context['managed_users']])
        self.assertNotIn('purchase_staff', [u.username for u in resp.context['managed_users']])
        self.assertNotIn('accounts_staff', [u.username for u in resp.context['managed_users']])

        # Store Admin can create a new store user
        create_resp = self.client.post(reverse('portal:user_create'), {
            'username': 'new_store_assistant',
            'email': 'assistant@test.com',
            'first_name': 'New',
            'last_name': 'Assistant',
            'password': 'password123',
            'confirm_password': 'password123',
            'unit_id': str(self.unit.id),
        })
        self.assertEqual(create_resp.status_code, 302)
        new_u = User.objects.get(username='new_store_assistant')
        self.assertEqual(new_u.role, RoleChoices.STORE)
        self.assertFalse(new_u.is_department_admin)

        # Store Admin can update password for store staff
        pwd_resp = self.client.post(reverse('portal:user_update_password', args=[self.store_user.id]), {
            'new_password': 'newpassword456',
            'confirm_password': 'newpassword456',
        })
        self.assertEqual(pwd_resp.status_code, 302)
        self.store_user.refresh_from_db()
        self.assertTrue(self.store_user.check_password('newpassword456'))

        # Store Admin CANNOT update password for accounts staff
        pwd_denied = self.client.post(reverse('portal:user_update_password', args=[self.accounts_user.id]), {
            'new_password': 'hackedpassword',
            'confirm_password': 'hackedpassword',
        })
        self.accounts_user.refresh_from_db()
        self.assertFalse(self.accounts_user.check_password('hackedpassword'))

    def test_superadmin_creates_department_admin(self):
        self.client.login(username="admin_user", password="password123")
        
        # Superadmin sees all users
        list_resp = self.client.get(reverse('portal:user_list'))
        self.assertEqual(list_resp.status_code, 200)
        usernames = [u.username for u in list_resp.context['managed_users']]
        self.assertIn('store_staff', usernames)
        self.assertIn('purchase_staff', usernames)
        self.assertIn('accounts_staff', usernames)

        # Superadmin creates an Accounts Department Admin
        resp = self.client.post(reverse('portal:user_create'), {
            'username': 'new_accounts_lead',
            'email': 'accts.lead@test.com',
            'first_name': 'Accounts',
            'last_name': 'Lead',
            'role': RoleChoices.ACCOUNTS,
            'is_department_admin': '1',
            'password': 'password123',
            'confirm_password': 'password123',
            'unit_id': str(self.unit.id),
        })
        self.assertEqual(resp.status_code, 302)
        lead = User.objects.get(username='new_accounts_lead')
        self.assertEqual(lead.role, RoleChoices.ACCOUNTS)
        self.assertTrue(lead.is_department_admin)
        self.assertTrue(lead.is_accounts_admin)

    def test_google_login_view(self):
        # Unauthenticated user visiting google login page
        response = self.client.get(reverse('portal:google_login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/google_dev_provider.html')

        # Already authenticated user should be redirected to workspace
        self.client.login(username="store_staff", password="password123")
        auth_response = self.client.get(reverse('portal:google_login'))
        self.assertEqual(auth_response.status_code, 302)
        self.assertIn('/store/', auth_response.url)

    def test_google_callback_single_user(self):
        # Sign-in with store@test.com should log in store_user and redirect to store portal
        response = self.client.post(reverse('portal:google_callback'), {'email': 'store@test.com'})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/store/', response.url)
        self.assertEqual(str(self.client.session['_auth_user_id']), str(self.store_user.id))

    def test_google_callback_multiple_users_and_select(self):
        # Create a second user sharing store@test.com
        shared_user = User.objects.create_user(
            username="store_assistant_shared",
            password="password123",
            role=RoleChoices.STORE,
            primary_unit=self.unit,
            email="store@test.com"
        )

        # Callback should render account picker
        response = self.client.post(reverse('portal:google_callback'), {'email': 'store@test.com'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/google_account_picker.html')
        self.assertEqual(self.client.session.get('pending_google_email'), 'store@test.com')

        # Select the second user
        select_response = self.client.post(reverse('portal:google_select_account'), {
            'user_id': str(shared_user.id)
        })
        self.assertEqual(select_response.status_code, 302)
        self.assertIn('/store/', select_response.url)
        self.assertEqual(str(self.client.session['_auth_user_id']), str(shared_user.id))

    def test_google_callback_unregistered_email(self):
        # An unprovisioned email should be blocked with unregistered policy notice
        response = self.client.post(reverse('portal:google_callback'), {'email': 'stranger@gmail.com'})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'registration/google_unregistered.html')
        self.assertNotIn('_auth_user_id', self.client.session)

