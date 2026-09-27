from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase
from rest_framework.views import APIView

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant


class ProtectedView(APIView):
    """Uses the default auth and permission settings, like every tenant-scoped view."""

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response({'tenant_id': str(request.auth.id)})


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


class ApiKeyAuthenticationTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = ProtectedView.as_view()

    def get(self, **headers):
        return self.view(self.factory.get('/protected', headers=headers))

    def test_missing_key_returns_401(self):
        response = self.get()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['WWW-Authenticate'], 'X-API-Key')

    def test_empty_key_returns_401(self):
        self.assertEqual(self.get(**{'X-API-Key': ''}).status_code, 401)

    def test_unknown_key_returns_401(self):
        create_tenant('Acme')
        response = self.get(**{'X-API-Key': generate_api_key()})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['WWW-Authenticate'], 'X-API-Key')

    def test_each_key_resolves_to_its_own_tenant(self):
        acme, acme_key = create_tenant('Acme')
        globex, globex_key = create_tenant('Globex')

        response = self.get(**{'X-API-Key': acme_key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tenant_id'], str(acme.id))

        response = self.get(**{'X-API-Key': globex_key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['tenant_id'], str(globex.id))


class ApiKeySchemaTests(APITestCase):
    def test_schema_declares_api_key_header_scheme(self):
        generator = SchemaGenerator(patterns=[path('protected', ProtectedView.as_view())])
        schema = generator.get_schema(request=None, public=True)

        self.assertEqual(
            schema['components']['securitySchemes']['ApiKeyAuth'],
            {'type': 'apiKey', 'in': 'header', 'name': 'X-API-Key'},
        )
        self.assertEqual(schema['paths']['/protected']['get']['security'], [{'ApiKeyAuth': []}])
