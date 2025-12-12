"""
This will make sure the app is always imported when
Django starts so that shared_task will use this app.
"""
from .celery import app as celery_app

# Import tasks to ensure they're registered with Celery
# This import happens after Django is initialized, so it's safe
try:
    from . import tasks  # noqa: F401
except ImportError:
    # Tasks module might not be available during initial import
    pass

__all__ = ('celery_app',)

