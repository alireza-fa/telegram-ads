import logging
from celery import shared_task
from .services.service_registry import get_crawler_lifecycle_service

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    name='process_crawler_task'
)
def process_crawler_task(self, task_id: int):
    """
    Background Celery task to execute a crawler job.
    Delegates the actual business logic to CrawlerLifecycleService.
    """
    logger.info(f"🚀 Starting execution for CrawlerTask ID: {task_id}")

    try:
        crawler_svc = get_crawler_lifecycle_service()
        crawler_svc.execute_crawling(task_id)

        logger.info(f"✅ Finished execution for CrawlerTask ID: {task_id}")

    except Exception as exc:
        logger.error(f"❌ Catastrophic failure in CrawlerTask ID {task_id}: {str(exc)}")
        raise self.retry(exc=exc)
