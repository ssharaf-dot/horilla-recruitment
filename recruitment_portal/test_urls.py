from django.http import HttpResponse
from django.urls import path
from .urls import urlpatterns

urlpatterns = urlpatterns + [path('careers/account/', lambda request: HttpResponse('applicant'), name='applicant-home'), path('careers/account/sign-in/', lambda request: HttpResponse('applicant'), name='applicant-login'), path('login/', lambda request: HttpResponse('login'), name='login')]
