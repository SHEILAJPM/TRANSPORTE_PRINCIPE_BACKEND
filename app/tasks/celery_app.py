from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("transporte_principe", broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)

celery_app.conf.beat_schedule = {
    "revisar-vencimientos-diario": {
        "task": "app.tasks.alertas_tasks.revisar_vencimientos",
        "schedule": crontab(hour=6, minute=0),
    },
}
celery_app.autodiscover_tasks(["app.tasks"])
