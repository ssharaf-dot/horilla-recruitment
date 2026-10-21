from django.urls import path
from . import views

urlpatterns = [
    path('careers/', views.careers, name='portal-careers'),
    path('careers/jobs/<int:pk>/', views.job_detail, name='portal-job-detail'),
    path('careers/jobs/<int:pk>/apply/', views.apply, name='portal-apply'),
    path('careers/application-received/', views.application_received, name='portal-application-received'),
    path('careers/brand/banner/', views.banner, name='portal-banner'),
    path('careers/brand/logo/', views.logo, name='portal-logo'),
    path('settings/portal/', views.branding, name='portal-branding'),
]
