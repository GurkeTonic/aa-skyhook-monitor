"""App Configuration"""

from django.apps import AppConfig

from aa_skyhook_monitor import __version__


class AaSkyhookMonitorConfig(AppConfig):
    default_auto_field = "django.db.models.AutoField"
    name = "aa_skyhook_monitor"
    label = "aa_skyhook_monitor"
    verbose_name = f"Skyhook Monitor v{__version__}"

    def ready(self):
        from celery import current_app
        from celery.schedules import crontab

        current_app.conf.beat_schedule["aa_skyhook_monitor_update_all"] = {
            "task": "aa_skyhook_monitor.tasks.update_all_skyhooks",
            "schedule": crontab(minute=0),
            "apply_offset": True,
        }
        current_app.conf.beat_schedule["aa_skyhook_monitor_check_notifications"] = {
            "task": "aa_skyhook_monitor.tasks.check_skyhook_notifications",
            "schedule": crontab(minute="*/5"),
            "apply_offset": True,
        }
