import os

broker_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
result_backend = os.environ.get("REDIS_URL", "redis://redis:6379/0")

worker_concurrency = 1
worker_prefetch_multiplier = 1
task_acks_late = True
task_reject_on_worker_lost = True
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True
beat_scheduler = "tasks:DatabaseScheduler"
result_expires = 86400
