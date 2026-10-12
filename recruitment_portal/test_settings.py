from recruitment_workspace.test_settings import *
from pathlib import Path
from tempfile import gettempdir

ROOT_URLCONF = 'recruitment_portal.test_urls'
MEDIA_ROOT = str(Path(gettempdir()) / 'horilla-portal-test-media')
STATIC_URL = '/static/'
MIDDLEWARE = MIDDLEWARE + ['django.contrib.messages.middleware.MessageMiddleware']
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates',
              'DIRS': [Path(__file__).resolve().parents[1] / 'templates'], 'APP_DIRS': True,
              'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                    'django.contrib.auth.context_processors.auth', 'recruitment_portal.tests.brand_context']}}]
