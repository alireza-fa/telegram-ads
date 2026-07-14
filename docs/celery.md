celery -A config worker -l info -P gevent -c 100

sh -c "rm -f celerybeat.pid && celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler"