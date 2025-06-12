from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    path('employees/', views.employee_list, name='employee_list'),
    path('employees/create/', views.employee_create, name='employee_create'),
    path('employees/<int:pk>/update/', views.employee_update, name='employee_update'),
    path('employees/<int:pk>/delete/', views.employee_delete, name='employee_delete'),

    path('attendance/', views.attendance_list, name='attendance_list'),
    path('attendance/bulk/', views.bulk_attendance_create, name='bulk_attendance_create'),
    path('attendance/<int:pk>/update/', views.attendance_update, name='attendance_update'),
    path('attendance/<int:pk>/delete/', views.attendance_delete, name='attendance_delete'),

    path('attendance/import/', views.attendance_import, name='attendance_import'),
    path('attendance/export/', views.attendance_export, name='attendance_export'),
    path('attendance/individual/', views.individual_attendance_create, name='select_employee_attendance'),
    path('attendance/individual/<int:employee_id>/', views.individual_attendance_create, name='individual_attendance_create'),

    path('dayoff/', views.dayoff_list, name='dayoff_list'),
    path('dayoff/create/', views.dayoff_create, name='dayoff_create'),
    path('dayoff/<int:pk>/delete/', views.dayoff_delete, name='dayoff_delete'),

    path('statistics/', views.attendance_statistics, name='attendance_statistics'),
    path('dashboard/', views.dashboard, name='dashboard'),
]
