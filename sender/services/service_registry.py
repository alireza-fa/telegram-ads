from functools import cache


@cache
def get_sender_lifecycle_service():
    from sender.services.lifecycle import SenderLifecycleService
    return SenderLifecycleService()
