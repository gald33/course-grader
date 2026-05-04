from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def safe_delay(task: Any, *args: Any, **kwargs: Any) -> str | None:
    try:
        result = task.apply_async(args=args, kwargs=kwargs, retry=False, ignore_result=True)
        return getattr(result, "id", None)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to enqueue task %s: %s", getattr(task, "name", str(task)), exc)
        return None
