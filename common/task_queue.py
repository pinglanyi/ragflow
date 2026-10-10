"""Shared Redis stream routing for API producers, workers and diagnostics."""

import os
import re


def task_queue_name(priority: int, base: str = "te") -> str:
    namespace = os.environ.get("RAGFLOW_TASK_QUEUE_NAMESPACE", "")
    if namespace and not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", namespace):
        raise ValueError("RAGFLOW_TASK_QUEUE_NAMESPACE must contain 1-80 letters, digits, underscores or hyphens")
    prefix = f"{base}.{namespace}" if namespace else base
    return f"{prefix}.{priority}.common"


def task_queue_names() -> list[str]:
    return [task_queue_name(priority) for priority in (1, 0)]
