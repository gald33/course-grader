from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "course_grader",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_publish_retry=False,
    broker_connection_retry_on_startup=False,
    broker_connection_max_retries=0,
)

celery_app.autodiscover_tasks(["app.tasks.jobs"])
