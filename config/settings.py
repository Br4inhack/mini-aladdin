"""
Django settings for mini-aladdin (CRPMS Portfolio Management System).
"""

import os
import platform
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env
load_dotenv(BASE_DIR / '.env')

# ─── Core ─────────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')

# ─── Applications ─────────────────────────────────────────────────────────────

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'channels',             # Django Channels — must come before staticfiles
    'rest_framework',
    'django_celery_beat',
    'django_celery_results',
]

LOCAL_APPS = [
    'apps.data_ingestion',
    'apps.feature_engine',
    'apps.agents',
    'apps.agents.sentiment_agent',
    'apps.portfolio',
    'apps.decision_engine',
    'apps.backtester',
    'apps.dashboard',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ─── Middleware ────────────────────────────────────────────────────────────────

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

# ─── Templates ────────────────────────────────────────────────────────────────

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

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION  = 'config.asgi.application'

# ─── Database ─────────────────────────────────────────────────────────────────

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('DB_NAME', 'portfolio_db'),
        'USER': os.getenv('DB_USER', 'portfolio_user'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
        'HOST': os.getenv('DB_HOST', '127.0.0.1'),
        'PORT': os.getenv('DB_PORT', '5432'),
        'OPTIONS': {
            'connect_timeout': 10,
        },
    }
}

# ─── Cache (Local Memory) ───────────────────────────────────────────────────

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# ─── Django Channels ───────────────────────────────────────────────────────────────

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

# ─── Password Validation ──────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ─── Internationalization ─────────────────────────────────────────────────────

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# ─── Static & Media Files ─────────────────────────────────────────────────────

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Django REST Framework ────────────────────────────────────────────────────

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

# ─── Celery ───────────────────────────────────────────────────────────────────

CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'Asia/Kolkata'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_RESULT_EXTENDED = True

# Task routing
CELERY_TASK_ROUTES = {
    'apps.data_ingestion.tasks.*': {'queue': 'data'},
    'apps.feature_engine.tasks.*': {'queue': 'features'},
    'apps.agents.tasks.*': {'queue': 'agents'},
    'apps.decision_engine.tasks.*': {'queue': 'decisions'},
    'apps.backtester.tasks.*': {'queue': 'backtest'},
}

# ─── Logging ──────────────────────────────────────────────────────────────────

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'crpms.log',
            'formatter': 'verbose',
            'delay': True,  # Only create file when first log is written
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'apps': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': True,
        },
    },
}

# ─── CRPMS System Thresholds ─────────────────────────────────────────────────

CRPMS = {
    # Risk thresholds
    'MAX_PORTFOLIO_VAR': 0.02,               # Max 2% daily Value-at-Risk
    'MAX_DRAWDOWN_THRESHOLD': 0.10,          # 10% drawdown triggers guard activation
    'DRAWDOWN_RECOVERY_THRESHOLD': 0.07,     # 7% drawdown to deactivate guard (hysteresis)
    'DRAWDOWN_GUARD_ENABLED': True,          # Master on/off switch for DrawdownGuard
    'RISK_SCORE_EXIT_THRESHOLD': 80,         # Risk score ≥ 80 → exit position
    'RISK_SCORE_REDUCE_THRESHOLD': 60,       # Risk score ≥ 60 → reduce exposure

    # Decision engine thresholds
    'REALLOCATION_SCORE_MARGIN': 20,         # Min score margin to trigger reallocation
    'OPPORTUNITY_ALERT_THRESHOLD': 75,       # Opportunity score to surface an alert

    # Sentiment
    'SENTIMENT_WINDOW_HOURS': 24,            # Rolling window for sentiment aggregation

    # Position management
    'STOP_LOSS_THRESHOLD': -0.08,            # -8% stop-loss from entry price

    # Correlation & concentration
    'CORRELATION_HIGH_THRESHOLD': 0.75,      # Asset pair correlation above this is high
    'SECTOR_CONCENTRATION_LIMIT': 0.40,      # Max 40% of NAV in any single sector

    # Agent output freshness
    'AGENT_OUTPUT_TTL_SECONDS': 3600,        # Agent outputs expire after 1 hour

    # Agent weights (must sum to 1.0)
    'AGENT_WEIGHTS': {
        'momentum': 0.25,
        'mean_reversion': 0.20,
        'sentiment': 0.20,
        'macro': 0.15,
        'ml_predictor': 0.20,
    },

    # Backtester defaults
    'BACKTEST_DEFAULT_INITIAL_CAPITAL': 100_000,
    'BACKTEST_DEFAULT_COMMISSION': 0.001,    # 0.1%
    'BACKTEST_DEFAULT_SLIPPAGE': 0.0005,     # 0.05%

    # Market data sources
    'DEFAULT_PRICE_SOURCE': 'yfinance',
    'DEFAULT_SENTIMENT_SOURCES': ['newsapi', 'reddit'],
    'MACRO_DATA_SOURCE': 'fred',

    # ... all existing keys stay ...
    'LLM_PRIMARY_MODEL':   'gemini-2.0-flash',
    'LLM_FALLBACK_MODEL':  'llama-3.3-70b-versatile',
    'LLM_MAX_TOKENS':       800,
    'LLM_ENABLED':          False,  # set False to fall back to templates instantly
    'CHANNELS_ENABLED':     True,   # Django Channels / WebSocket support
}

# ─── Feature Flags ────────────────────────────────────────────────────────────
# All set to False initially; enable per-environment via .env or deployment config.

FEATURES = {
    # Enable the ML-based risk scoring agent (requires trained model in /models)
    'ML_RISK_AGENT': False,

    # Enable FinBERT NLP sentiment analysis (slower, more accurate than VADER)
    'FINBERT_SENTIMENT': False,

    # Enable live WebSocket price feeds (requires broker WebSocket API credentials)
    'LIVE_WEBSOCKET': False,

    # Enable paper-trading mode (simulated order execution, no real money moved)
    'PAPER_TRADING': False,
}

# ─── External API Keys (loaded from .env) ─────────────────────────────────────

NEWSAPI_KEY = os.getenv('NEWSAPI_KEY', '')
REDDIT_CLIENT_ID = os.getenv('REDDIT_CLIENT_ID', '')
REDDIT_CLIENT_SECRET = os.getenv('REDDIT_CLIENT_SECRET', '')
REDDIT_USER_AGENT = os.getenv('REDDIT_USER_AGENT', 'mini-aladdin-bot/1.0')
FRED_API_KEY = os.getenv('FRED_API_KEY', '')

# ─── Windows-Specific Fixes ───────────────────────────────────────────────────

if platform.system() == 'Windows':
    # Celery on Windows requires solo pool (set in CLI: --pool=solo)
    # This env var signals that we are in a Windows multiprocessing context
    os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')

# ─── Celery Beat Schedule ─────────────────────────────────────────────────────

from config.celery_schedule import *

