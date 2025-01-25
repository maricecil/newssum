from pathlib import Path
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# OpenAI API 키 설정
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = [
    '127.0.0.1', 
    'localhost', 
    '54.180.108.226', 
    'newssum.ngrok.io',
    'newssum.ngrok.app',
    '300170253994.ngrok.app'
    '*.ngrok.app',  # Allow all ngrok subdomains
    '.ngrok.io',  # 추가
    '*ngrok.io',  # 추가
]

CSRF_TRUSTED_ORIGINS = [
    'https://newssum.ngrok.io',
    'http://newssum.ngrok.io',  # http도 추가
    'https://newssum.jp.ngrok.io',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'news',
]

CRON_CLASSES = [
    'news.cron.AutoSummaryCronJob',
]

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
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
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
]

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Root URL Configuration
ROOT_URLCONF = 'newsdocs.urls'

# WSGI Application
WSGI_APPLICATION = 'newsdocs.wsgi.application'

# Secret Key
SECRET_KEY = 'django-insecure-your-secret-key-here'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
} 

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LOGGING 설정 추가
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'logs', 'django.log'),
            'encoding': 'utf-8',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'news': {  # news 앱의 로그
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'crawling': {  # 크롤링 모듈의 로그
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# logs 디렉토리 생성
if not os.path.exists(os.path.join(BASE_DIR, 'logs')):
    os.makedirs(os.path.join(BASE_DIR, 'logs'))

# API 타임아웃 설정
API_TIMEOUT = 300  # API 호출 타임아웃 (초)
CACHE_TIMEOUT = 3600  # 캐시 타임아웃 (30분)

# 캐시 설정 수정
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': CACHE_TIMEOUT,
        'OPTIONS': {
            'MAX_ENTRIES': 1000,  # 최대 캐시 항목 수
            'CULL_FREQUENCY': 3,  # 정리 빈도
        }
    }
}

# API 타임아웃 설정
API_TIMEOUT = 30  # 초 단위

# 연결 재시도 설정
MAX_RETRIES = 3
RETRY_BACKOFF = 1  # 초 단위

# 시간 설정
TIME_ZONE = 'Asia/Seoul'
USE_TZ = True
