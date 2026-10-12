"""Isolated tests: no Horilla app startup, schedulers or production database."""

SECRET_KEY = "only-for-local-recruitment-mode-tests"
RECRUITMENT_ONLY = True
ALLOWED_HOSTS = ["testserver"]
ROOT_URLCONF = "recruitment_workspace.tests"
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "recruitment_portal",
]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
# The installed image adds an auth migration for Horilla's dynamically extended
# User model. These isolated tests intentionally use vanilla Django's User.
MIGRATION_MODULES = {"auth": None}
MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "recruitment_workspace.recruitment_mode.RecruitmentOnlyMiddleware",
]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
