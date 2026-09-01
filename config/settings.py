"""
Django settings for EntailsNG project.
"""

import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# .env aus BASE_DIR laden (falls vorhanden)
load_dotenv(BASE_DIR / '.env')


def env_bool(key, default=False):
    """Parst eine Boolean-Umgebungsvariable robust und sicher."""
    val = os.environ.get(key)
    if val is None:
        return default
    return str(val).strip().lower() in ('true', '1', 't', 'yes')


# -----------------------------------------------------------------------------
# Basis & Core-Sicherheit (Fail-Fast Validierung)
# -----------------------------------------------------------------------------
DEBUG = env_bool('DEBUG', default=False)

SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "Umgebungsvariable SECRET_KEY ist zwingend erforderlich und darf nicht leer sein!"
    )

FIELD_ENCRYPTION_KEY = os.environ.get('FIELD_ENCRYPTION_KEY', '')
if not FIELD_ENCRYPTION_KEY and not DEBUG and 'test' not in sys.argv:
    import warnings
    warnings.warn(
        "FIELD_ENCRYPTION_KEY ist nicht gesetzt. Gespeicherte SMTP-Passwörter "
        "werden mit dem SECRET_KEY verschlüsselt und sind nach dessen Änderung "
        "unlesbar.",
        RuntimeWarning,
    )

ALLOWED_HOSTS_ENV = os.environ.get('ALLOWED_HOSTS')
if ALLOWED_HOSTS_ENV:
    ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_ENV.split(',') if h.strip()]
elif DEBUG:
    ALLOWED_HOSTS = ['*']
else:
    raise ImproperlyConfigured(
        "Umgebungsvariable ALLOWED_HOSTS muss im Produktionsbetrieb (DEBUG=False) zwingend konfiguriert sein!"
    )

CSRF_TRUSTED_ORIGINS_ENV = os.environ.get('CSRF_TRUSTED_ORIGINS')
if CSRF_TRUSTED_ORIGINS_ENV:
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in CSRF_TRUSTED_ORIGINS_ENV.split(',') if o.strip()]
else:
    CSRF_TRUSTED_ORIGINS = []


# -----------------------------------------------------------------------------
# Application definition
# -----------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # EntailsNG Apps:
    'users',
    'tinymce',
    'events',
    'configuration',
    'seating',
    'info',
    'news',
    'clans',
    'emails',
    'tournaments',
    'sponsors',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'configuration.middleware.DynamicDebugMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'configuration.context_processors.feature_flags',
                'emails.context_processors.email_status',
                'django.contrib.messages.context_processors.messages',
            ],
            'builtins': [
                'configuration.templatetags.translations',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# -----------------------------------------------------------------------------
# Datenbank-Konfiguration
# -----------------------------------------------------------------------------
DB_ENGINE = os.environ.get('DB_ENGINE', 'postgresql')

if DB_ENGINE == 'sqlite':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
else:
    db_name = os.environ.get('DB_NAME')
    db_user = os.environ.get('DB_USER')
    db_password = os.environ.get('DB_PASSWORD')
    db_host = os.environ.get('DB_HOST', 'db')
    db_port = os.environ.get('DB_PORT', '5432')

    if not DEBUG and 'test' not in sys.argv:
        missing_db_vars = []
        if not db_name:
            missing_db_vars.append('DB_NAME')
        if not db_user:
            missing_db_vars.append('DB_USER')
        if not db_password:
            missing_db_vars.append('DB_PASSWORD')
        if missing_db_vars:
            raise ImproperlyConfigured(
                f"Folgende Datenbank-Umgebungsvariablen fehlen für den Produktionsbetrieb: {', '.join(missing_db_vars)}"
            )

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': db_name or 'entailsng_db',
            'USER': db_user or 'entailsng',
            'PASSWORD': db_password or '',
            'HOST': db_host,
            'PORT': db_port,
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '600')),
        }
    }


# -----------------------------------------------------------------------------
# Cache Configuration (Redis für Multi-Worker Konsistenz)
# -----------------------------------------------------------------------------
REDIS_URL = os.environ.get('REDIS_URL')
if REDIS_URL and 'test' not in sys.argv:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
        }
    }
else:
    if not DEBUG and 'test' not in sys.argv:
        raise ImproperlyConfigured(
            "Umgebungsvariable REDIS_URL ist für den Produktionsbetrieb (DEBUG=False) zwingend erforderlich (Multi-Worker Cache Konsistenz)!"
        )
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'entailsng-local-cache',
        }
    }


# -----------------------------------------------------------------------------
# Password validation
# -----------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# -----------------------------------------------------------------------------
# Internationalization & Timezone
# -----------------------------------------------------------------------------
LANGUAGE_CODE = 'de'
TIME_ZONE = 'Europe/Vienna'
USE_I18N = True
USE_TZ = True


# -----------------------------------------------------------------------------
# Static files & Media Uploads
# -----------------------------------------------------------------------------
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

if not DEBUG and 'test' not in sys.argv:
    _staticfiles_storage_backend = "whitenoise.storage.CompressedManifestStaticFilesStorage"
else:
    _staticfiles_storage_backend = "whitenoise.storage.CompressedStaticFilesStorage"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": _staticfiles_storage_backend,
    },
}


MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
SERVE_MEDIA = env_bool('SERVE_MEDIA', default=DEBUG)

AUTH_USER_MODEL = 'users.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
LOGIN_URL = '/login/'

AUTHENTICATION_BACKENDS = [
    'users.auth_backends.EmailOrUsernameBackend',
]


# -----------------------------------------------------------------------------
# E-Mail Konfiguration (Standard SMTP)
# -----------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'emails.backends.ConfiguredSMTPBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', default=False)
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', '')
SERVER_EMAIL = os.environ.get('SERVER_EMAIL', DEFAULT_FROM_EMAIL)
EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', '10'))


# -----------------------------------------------------------------------------
# Reverse Proxy & HTTPS Security Header
# -----------------------------------------------------------------------------
BEHIND_PROXY = env_bool('BEHIND_PROXY', default=True)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
else:
    SECURE_PROXY_SSL_HEADER = None

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', default=True)
    SECURE_REDIRECT_EXEMPT = [
        r'^api/health/',
    ]
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', default=True)
    CSRF_COOKIE_SECURE = env_bool('CSRF_COOKIE_SECURE', default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

    # HSTS (HTTP Strict Transport Security)
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('SECURE_HSTS_INCLUDE_SUBDOMAINS', default=True)
    SECURE_HSTS_PRELOAD = env_bool('SECURE_HSTS_PRELOAD', default=True)


# -----------------------------------------------------------------------------
# Standardisiertes stdout Logging (für Docker Compose Logs)
# -----------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{asctime}] {levelname} [{name}:{lineno}] {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'stream': sys.stdout,
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': os.environ.get('DJANGO_LOG_LEVEL', 'INFO'),
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}



