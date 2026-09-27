from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from .serializers import TenantSerializer


@extend_schema(summary='Create a tenant', tags=['Tenants'])
class TenantCreateView(generics.CreateAPIView):
    """Create a tenant and its API key. The key is shown only in this response.

    Public: no API key is needed, since this creates the tenant that later
    requests are scoped to.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = TenantSerializer
