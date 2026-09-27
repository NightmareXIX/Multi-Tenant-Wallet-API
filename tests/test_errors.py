import json
import uuid

from django.test import RequestFactory, SimpleTestCase
from django.urls import get_resolver
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APITestCase

from tenants.authentication import generate_api_key, hash_api_key
from tenants.models import Tenant
from wallets.services import create_user


def create_tenant(name):
    key = generate_api_key()
    return Tenant.objects.create(name=name, api_key_hash=hash_api_key(key)), key


class ErrorShapeTests(APITestCase):
    """Every row of the Route Design status-code table, in the {"error": {...}} shape."""

    def setUp(self):
        self.acme, self.acme_key = create_tenant('Acme')
        self.globex, self.globex_key = create_tenant('Globex')
        self.wallet = create_user(self.acme, 'Alice').wallet
        self.bob = create_user(self.acme, 'Bob').wallet
        self.client.credentials(HTTP_X_API_KEY=self.acme_key)

    def post(self, url, body, key='key-1'):
        headers = {} if key is None else {'Idempotency-Key': key}
        return self.client.post(url, body, format='json', headers=headers)

    def deposit_url(self, wallet_id):
        return f'/api/v1/wallets/{wallet_id}/deposit'

    def assertError(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(set(response.data), {'error'})
        error = response.data['error']
        self.assertEqual(error['code'], code)
        self.assertTrue(error['message'])
        return error

    def test_validation_error_names_each_bad_field(self):
        response = self.post(self.deposit_url(self.wallet.id), {'amount': '100'})

        error = self.assertError(response, 400, 'validation_error')
        self.assertEqual(set(error), {'code', 'message', 'fields'})
        self.assertEqual(error['fields'], {'amount': ['Must be an integer number of paisa.']})

    def test_balance_overflow_is_a_validation_error(self):
        self.post(self.deposit_url(self.wallet.id), {'amount': 2**63 - 1}, key='key-1')

        response = self.post(self.deposit_url(self.wallet.id), {'amount': 1}, key='key-2')

        error = self.assertError(response, 400, 'validation_error')
        self.assertIn('amount', error['fields'])

    def test_idempotency_key_missing(self):
        response = self.post(self.deposit_url(self.wallet.id), {'amount': 100}, key=None)
        error = self.assertError(response, 400, 'idempotency_key_missing')
        self.assertNotIn('fields', error)

    def test_same_wallet_transfer(self):
        body = {'source_wallet_id': str(self.wallet.id), 'destination_wallet_id': str(self.wallet.id), 'amount': 1}
        self.assertError(self.post('/api/v1/transfers', body), 400, 'same_wallet_transfer')

    def test_missing_api_key(self):
        self.client.credentials()
        response = self.client.get(f'/api/v1/wallets/{self.wallet.id}')
        self.assertError(response, 401, 'invalid_api_key')
        self.assertEqual(response['WWW-Authenticate'], 'X-API-Key')

    def test_unknown_api_key(self):
        self.client.credentials(HTTP_X_API_KEY=generate_api_key())
        response = self.client.get(f'/api/v1/wallets/{self.wallet.id}')
        self.assertError(response, 401, 'invalid_api_key')
        self.assertEqual(response['WWW-Authenticate'], 'X-API-Key')

    def test_other_tenants_wallet_looks_like_a_missing_one(self):
        missing = self.client.get(f'/api/v1/wallets/{uuid.uuid4()}')
        self.client.credentials(HTTP_X_API_KEY=self.globex_key)
        other_tenants = self.client.get(f'/api/v1/wallets/{self.wallet.id}')

        self.assertError(missing, 404, 'not_found')
        self.assertError(other_tenants, 404, 'not_found')
        self.assertEqual(other_tenants.data, missing.data)

    def test_page_out_of_range(self):
        response = self.client.get(f'/api/v1/wallets/{self.wallet.id}/transactions', {'page': 2})
        self.assertError(response, 404, 'not_found')

    def test_insufficient_funds(self):
        response = self.post(f'/api/v1/wallets/{self.wallet.id}/withdraw', {'amount': 1})
        self.assertError(response, 422, 'insufficient_funds')

    def test_idempotency_key_mismatch(self):
        self.post(self.deposit_url(self.wallet.id), {'amount': 100})
        response = self.post(self.deposit_url(self.wallet.id), {'amount': 200})
        self.assertError(response, 422, 'idempotency_key_mismatch')

    def test_malformed_json_keeps_the_shape(self):
        response = self.client.post(
            self.deposit_url(self.wallet.id),
            '{"amount": ',
            content_type='application/json',
            headers={'Idempotency-Key': 'key-1'},
        )
        self.assertError(response, 400, 'parse_error')


class DjangoErrorViewTests(SimpleTestCase):
    """Errors raised before any DRF view runs still use the error shape."""

    def assertJsonError(self, response, status, code):
        self.assertEqual(response.status_code, status)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(json.loads(response.content)['error']['code'], code)

    def test_malformed_wallet_id_returns_json_404(self):
        # The <uuid:> converter rejects it in URL routing, before auth.
        self.assertJsonError(self.client.get('/api/v1/wallets/not-a-uuid'), 404, 'not_found')

    def test_unknown_path_returns_json_404(self):
        self.assertJsonError(self.client.get('/api/v1/nope'), 404, 'not_found')

    def test_server_error_returns_json_500(self):
        handler = get_resolver().resolve_error_handler(500)
        self.assertJsonError(handler(RequestFactory().get('/')), 500, 'server_error')


class ErrorSchemaTests(SimpleTestCase):
    """/api/docs shows the error shape under each status a route can return."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def response_refs(self, path, method):
        responses = self.schema['paths'][path][method]['responses']
        return {status: r['content']['application/json']['schema']['$ref'] for status, r in responses.items()}

    def test_error_component_has_the_error_shape(self):
        schemas = self.schema['components']['schemas']
        self.assertEqual(schemas['Error']['properties'], {'error': {'$ref': '#/components/schemas/ErrorDetail'}})
        self.assertEqual(set(schemas['ErrorDetail']['properties']), {'code', 'message', 'fields'})
        self.assertEqual(schemas['ErrorDetail']['required'], ['code', 'message'])

    def test_money_route_documents_each_error_status(self):
        error = '#/components/schemas/Error'
        self.assertEqual(
            self.response_refs('/api/v1/wallets/{wallet_id}/withdraw', 'post'),
            {'201': '#/components/schemas/Transaction', '400': error, '401': error, '404': error, '422': error},
        )

    def test_history_success_is_still_paginated(self):
        refs = self.response_refs('/api/v1/wallets/{wallet_id}/transactions', 'get')
        self.assertEqual(refs['200'], '#/components/schemas/PaginatedTransactionList')
        self.assertEqual(refs['404'], '#/components/schemas/Error')
