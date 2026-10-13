"""Run queued background jobs: `python -m app.tasks.worker`.

Connects to the same database as the API (DATABASE_URL), so it can run on the
instructor's machine while the API is hosted elsewhere.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

import app.tasks.jobs  # noqa: F401  (registers the job functions)
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.tasks.queue import claim_next, requeue_stale, run_job, worker_id

logger = logging.getLogger("app.tasks.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    stopping = False

    def stop(*_: object) -> None:
        nonlocal stopping
        stopping = True
        logger.info("Stopping after the current job")

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    me = worker_id()
    stale_after = timedelta(minutes=settings.job_stale_minutes)
    logger.info("Worker %s polling every %ss", me, settings.worker_poll_seconds)
    last_stale_check = 0.0
    while not stopping:
        with SessionLocal() as db:
            if time.monotonic() - last_stale_check > 60:
                if requeued := requeue_stale(db, stale_after):
                    logger.warning("Re-queued %d stale job(s)", requeued)
                last_stale_check = time.monotonic()
            row = claim_next(db, me)
            if row is not None:
                logger.info("Running job %s %s", row.id, row.name)
                run_job(db, row)
                logger.info("Job %s %s", row.id, row.status)
                continue
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
