from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'api'

router = DefaultRouter()
router.register(r'receipts', views.GoodsReceiptViewSet, basename='receipt')
router.register(r'invoices', views.InvoiceViewSet, basename='invoice')
router.register(r'handovers', views.HandoverBatchViewSet, basename='handover')
router.register(r'tasks', views.WorkflowTaskViewSet, basename='task')
router.register(r'thresholds', views.ApprovalThresholdViewSet, basename='threshold')

urlpatterns = [
    path('', include(router.urls)),
]
