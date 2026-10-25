# Worker

The worker runs the same `aseo` package as the API. Start it with:

```bash
cd apps/api && .venv/bin/celery -A aseo.worker.celery_app worker -l info --pool threads --concurrency 4
cd apps/api && .venv/bin/celery -A aseo.worker.celery_app beat -l info
```

Set `TASK_EXECUTION=celery` on the API so it signals the relay instead of draining the
outbox in-process. In production run `worker` and `beat` as separate processes
(`celery ... worker` and `celery ... beat`) so only one beat instance exists.
