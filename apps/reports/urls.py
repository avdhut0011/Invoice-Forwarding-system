from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.reports_summary_view, name='summary'),
    path('export/excel/', views.export_excel_report, name='export_excel'),
]
