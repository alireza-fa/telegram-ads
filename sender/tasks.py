import logging
from celery import shared_task

from .services.service_registry import get_sender_lifecycle_service

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    name='process_sender_task'
)
def process_sender_task(self, task_id: int):
    """
    Background Celery task to execute a sender campaign.
    Delegates the actual business logic to SenderLifecycleService.
    """
    logger.info("🚀 Starting execution for SenderTask ID: %s", task_id)

    try:
        sender_svc = get_sender_lifecycle_service()
        sender_svc.execute_sending(task_id)

        logger.info("✅ Finished execution for SenderTask ID: %s", task_id)

    except Exception as exc:
        logger.exception("❌ Catastrophic failure in SenderTask ID %s", task_id)
        raise self.retry(exc=exc)
