import hashlib
import secrets

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import Tenant

API_KEY_HEADER = 'X-API-Key'


def generate_api_key():
    return 'sk_' + secrets.token_urlsafe(32)


def hash_api_key(key):
    # SHA-256 is enough for a long random key; bcrypt would slow every request.
    return hashlib.sha256(key.encode()).hexdigest()


class ApiKeyAuthentication(BaseAuthentication):
    """Resolves the tenant from the X-API-Key header and puts it on request.auth.

    There is no end user: the caller is the tenant's own backend, so
    request.user stays anonymous.
    """

    def authenticate(self, request):
        key = request.headers.get(API_KEY_HEADER)
        if not key:
            # Not attempted; the HasTenant permission turns this into a 401.
            return None
        tenant = Tenant.objects.filter(api_key_hash=hash_api_key(key)).first()
        if tenant is None:
            raise AuthenticationFailed('Invalid API key.')
        return AnonymousUser(), tenant

    def authenticate_header(self, request):
        # Without a WWW-Authenticate value DRF downgrades 401 to 403.
        return API_KEY_HEADER
