from django.apps import AppConfig


class AaSkyhookMonitorConfig(AppConfig):
    name = 'aa_skyhook_monitor'
    label = 'aa_skyhook_monitor'
    verbose_name = 'Skyhook Monitor'

    def ready(self):
        from celery import current_app
        from celery.schedules import crontab

        current_app.conf.beat_schedule['aa_skyhook_monitor_update_all'] = {
            'task': 'aa_skyhook_monitor.tasks.update_all_skyhooks',
            'schedule': crontab(minute=0),
        }
