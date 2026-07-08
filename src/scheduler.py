"""Taskiq scheduler entrypoint.

Run with: ``taskiq scheduler scheduler:scheduler <task-modules> --app-dir=src``.
Uses LabelScheduleSource so any ``@broker.task(schedule=[...])`` (e.g.
``processing.chat_tasks.index_chat_messages``) is picked up automatically.
"""

from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource

from broker import broker

scheduler = TaskiqScheduler(broker, sources=[LabelScheduleSource(broker)])
