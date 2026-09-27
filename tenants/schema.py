from drf_spectacular.extensions import OpenApiAuthenticationExtension

from .authentication import API_KEY_HEADER


class ApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    """Describes ApiKeyAuthentication so Swagger's Authorize button sends X-API-Key."""

    target_class = 'tenants.authentication.ApiKeyAuthentication'
    name = 'ApiKeyAuth'

    def get_security_definition(self, auto_schema):
        return {'type': 'apiKey', 'in': 'header', 'name': API_KEY_HEADER}
