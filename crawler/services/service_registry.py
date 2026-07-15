from functools import cache

@cache
def get_crawler_lifecycle_service():
    from crawler.services.lifecycle import CrawlerLifecycleService
    return CrawlerLifecycleService()
