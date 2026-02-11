from django.apps import AppConfig


class BarkatConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'barkat'

    def ready(self):
        import barkat.signals
