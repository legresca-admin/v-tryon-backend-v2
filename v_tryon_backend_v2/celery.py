"""
Celery configuration for v-tryon-backend-v2
"""
import os
import sys
import logging
from celery import Celery
from django.conf import settings

# Set default Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'v_tryon_backend_v2.settings')

# Create Celery app
app = Celery('v_tryon_backend_v2')

# Load config from Django settings with CELERY namespace
app.config_from_object('django.conf:settings', namespace='CELERY')

logger = logging.getLogger(__name__)

# Windows compatibility: Use 'solo' pool on Windows (prefork doesn't work on Windows)
if sys.platform == 'win32':
    app.conf.worker_pool = 'solo'
    logger.info("[CELERY CONFIG] Using 'solo' pool for Windows compatibility")

# Explicitly set broker URL
broker_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
app.conf.broker_url = broker_url
logger.info(f"[CELERY CONFIG] Broker URL: {broker_url}")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Task result backend
result_backend = getattr(settings, 'CELERY_RESULT_BACKEND', 'django-db')
app.conf.result_backend = result_backend
app.conf.result_extended = True
app.conf.broker_connection_retry_on_startup = True
logger.info(f"[CELERY CONFIG] Result backend: {result_backend}")

# Task serialization
app.conf.task_serializer = 'json'
app.conf.accept_content = ['json']
app.conf.result_serializer = 'json'

# Timezone
app.conf.timezone = 'UTC'
app.conf.enable_utc = True

# Task tracking
app.conf.task_track_started = True
app.conf.task_send_sent_event = True

# Retry configuration
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True

# Worker configuration
# Note: worker_prefetch_multiplier and worker_max_tasks_per_child don't apply to 'solo' pool
if sys.platform != 'win32':
    app.conf.worker_prefetch_multiplier = 1
    app.conf.worker_max_tasks_per_child = 50

# Task time limits
app.conf.task_time_limit = 600  # 10 minutes hard limit
app.conf.task_soft_time_limit = 540  # 9 minutes soft limit

