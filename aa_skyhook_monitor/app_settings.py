"""App Settings"""

from django.conf import settings

SKYHOOK_MONITOR_TASKS_TIME_LIMIT = getattr(
    settings, "SKYHOOK_MONITOR_TASKS_TIME_LIMIT", 1200
)

SKYHOOK_MONITOR_WARNING_MINUTES = getattr(
    settings, "SKYHOOK_MONITOR_WARNING_MINUTES", 30
)
