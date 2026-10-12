from django.http import HttpResponse
from django.urls import path
from .urls import urlpatterns

urlpatterns = urlpatterns + [path('login/', lambda request: HttpResponse('login'), name='login')]
