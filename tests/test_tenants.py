from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APITestCase

from tenants.authentication import hash_api_key
from tenants.models import Tenant

URL = '/api/v1/tenants'


class CreateTenantTests(APITestCase):
    def test_creates_tenant_and_returns_key_once(self):
        response = self.client.post(URL, {'name': 'Acme'}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(set(response.data), {'id', 'name', 'api_key', 'created_at'})
        self.assertEqual(response.data['name'], 'Acme')
        key = response.data['api_key']
        self.assertTrue(key.startswith('sk_'))

        tenant = Tenant.objects.get(id=response.data['id'])
        self.assertEqual(tenant.api_key_hash, hash_api_key(key))
        self.assertNotEqual(tenant.api_key_hash, key)

    def test_each_tenant_gets_a_different_key(self):
        first = self.client.post(URL, {'name': 'Acme'}, format='json').data['api_key']
        second = self.client.post(URL, {'name': 'Acme'}, format='json').data['api_key']
        self.assertNotEqual(first, second)

    def test_invalid_name_returns_400(self):
        for body in ({}, {'name': ''}, {'name': '   '}, {'name': 'x' * 256}):
            with self.subTest(body=body):
                response = self.client.post(URL, body, format='json')
                self.assertEqual(response.status_code, 400)
        self.assertFalse(Tenant.objects.exists())

    def test_ignores_api_key_header(self):
        response = self.client.post(
            URL, {'name': 'Acme'}, format='json', headers={'X-API-Key': 'sk_wrong'}
        )
        self.assertEqual(response.status_code, 201)

    def test_schema_marks_route_as_public(self):
        schema = SchemaGenerator().get_schema(request=None, public=True)
        # [{}] is OpenAPI for "no auth required".
        self.assertEqual(schema['paths'][URL]['post']['security'], [{}])
