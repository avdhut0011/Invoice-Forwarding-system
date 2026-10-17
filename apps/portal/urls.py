from django.urls import path
from . import views

app_name = 'portal'

urlpatterns = [
    # Auth
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('', views.dashboard_view, name='dashboard'),

    # Store Portal
    path('store/', views.store_portal_view, name='store_portal'),
    path('store/submit/', views.store_submit_view, name='store_submit'),
    path('store/handover/', views.store_handover_view, name='store_handover'),

    # Purchase Portal
    path('purchase/', views.purchase_portal_view, name='purchase_portal'),
    path('purchase/search-po/', views.purchase_search_po_view, name='purchase_search_po'),
    path('purchase/submit-bill/', views.purchase_bill_submit_view, name='purchase_bill_submit'),
    path('purchase/ack-custody/', views.purchase_ack_custody_view, name='purchase_ack_custody'),

    # Accounts Portal
    path('accounts/', views.accounts_portal_view, name='accounts_portal'),
    path('accounts/ack-custody/', views.accounts_ack_custody_view, name='accounts_ack_custody'),
    path('accounts/approve/', views.accounts_approve_view, name='accounts_approve'),
    path('accounts/return/', views.accounts_return_view, name='accounts_return'),
]
