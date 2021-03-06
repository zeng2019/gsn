"""
Django settings for mysite project.

Generated by 'django-admin startproject' using Django 1.8.3.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.8/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = '4z_g+i&5omq3lbl@%*t!r1(6ag)9o619n2w@!eu0y@lg=p2gmj'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = []

# Application definition

AUTH_USER_MODEL = "gsn.GSNUser"

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'djangobower',
    'gsn'
    )

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    )

ROOT_URLCONF = 'app.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [os.path.join(BASE_DIR, 'templates')],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': ['django.template.context_processors.debug',
                               'django.template.context_processors.request',
                               'django.contrib.auth.context_processors.auth',
                               'django.contrib.messages.context_processors.messages',
                               ],
        },
    }, ]

AUTHENTICATION_BACKENDS = (  # Default backend
    'django.contrib.auth.backends.ModelBackend',  # Additional backend
    'allaccess.backends.AuthorizedServiceBackend',
    )

WSGI_APPLICATION = 'app.wsgi.application'

# Database
# https://docs.djangoproject.com/en/1.8/ref/settings/#databases

BOWER_COMPONENTS_ROOT = os.path.join(BASE_DIR, 'components')

BOWER_INSTALLED_APPS = (
    "angularjs",
    "angular-route#^1.5.0",
    "angular-bootstrap-datetimepicker#^1.0.1",
    "angular-date-time-input",
    "dirPagination#^1.0.0",
    "angular-bootstrap#^1.1.2",
    "bootstrap#^3.3.6",
    "font-awesome#^4.5.0",
    "metisMenu#^2.4.0",
    "jquery",
    "jquery-ui#^1.11.4",
    "angular-tabs#^1.0.2",
    "angular-local-storage#^0.2.3",
    "ngmap#^1.16.7",
    "markerclustererplus#^2.1.4",
    "angular-chart.js#^0.9.0",
    "highcharts#^4.2.3",
    "highcharts-ng#^0.0.11",
    "ngAutocomplete#^1.0.0",
    "angular-spinner#^0.8.1",
    "moment#^2.11.2",
    "angular-websocket",
)

# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'CET'

USE_I18N = True

USE_L10N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.8/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = './static/'

STATICFILES_DIRS = (
    os.path.join(BASE_DIR, "static-files"),
)

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
    'djangobower.finders.BowerFinder',
)

# Custom setting

LOGIN_URL = '/login/'


try:
    from app.settingsLocal import *
except ImportError:
    raise