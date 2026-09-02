"""Общие помощники: темп действий, анти-инъекция."""

from profi.utils.pacing import human_pause, type_human
from profi.utils.textguard import has_contacts
from profi.utils.workhours import in_work_hours

__all__ = ["has_contacts", "human_pause", "in_work_hours", "type_human"]
