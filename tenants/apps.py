from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'

    def ready(self):
        # spectacular only finds the auth extension if its module is imported.
        from . import schema  # noqa: F401
