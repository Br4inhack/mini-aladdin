import os
import platform
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# Windows fix: prevents multiprocessing issues with Celery on Windows
if platform.system() == 'Windows':
    os.environ.setdefault('FORKED_BY_MULTIPROCESSING', '1')

app = Celery('mini_aladdin')

# Use CELERY_ prefix in Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks from all INSTALLED_APPS
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Celery debug task — prints request info."""
    print(f'Request: {self.request!r}')
