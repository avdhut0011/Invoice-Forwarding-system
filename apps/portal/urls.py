from django.urls import path
from . import views
from . import user_views
from . import oauth_views

app_name = 'portal'

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Google Sign-In OAuth
    path('oauth/google/', oauth_views.google_login_view, name='google_login'),
    path('oauth/google/callback/', oauth_views.google_callback_view, name='google_callback'),
    path('oauth/google/select-account/', oauth_views.google_select_account_view, name='google_select_account'),

    # Dashboard
    path('', views.dashboard_view, name='dashboard'),

    # Store Portal (Restricted to Store Department & Superadmin)
    path('store/', views.store_portal_view, name='store_portal'),
    path('store/submit/', views.store_submit_view, name='store_submit'),
    path('store/handover/', views.store_handover_view, name='store_handover'),

    # Purchase Portal (Restricted to Purchase Department & Superadmin)
    path('purchase/', views.purchase_portal_view, name='purchase_portal'),
    path('purchase/search-po/', views.purchase_search_po_view, name='purchase_search_po'),
    path('purchase/submit-bill/', views.purchase_bill_submit_view, name='purchase_bill_submit'),
    path('purchase/ack-custody/', views.purchase_ack_custody_view, name='purchase_ack_custody'),

    # Accounts Portal (Restricted to Accounts Department & Superadmin)
    path('accounts/', views.accounts_portal_view, name='accounts_portal'),
    path('accounts/ack-custody/', views.accounts_ack_custody_view, name='accounts_ack_custody'),
    path('accounts/approve/', views.accounts_approve_view, name='accounts_approve'),
    path('accounts/return/', views.accounts_return_view, name='accounts_return'),

    # Department-Aware User Management Console
    path('users/', user_views.user_list_view, name='user_list'),
    path('users/create/', user_views.user_create_view, name='user_create'),
    path('users/<uuid:user_id>/password/', user_views.user_update_password_view, name='user_update_password'),
    path('users/<uuid:user_id>/toggle-status/', user_views.user_toggle_status_view, name='user_toggle_status'),
]
