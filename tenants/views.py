from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.permissions import AllowAny

from wallets.serializers import ErrorSerializer

from .serializers import TenantSerializer


@extend_schema(
    summary='Create a tenant',
    tags=['Tenants'],
    responses={201: TenantSerializer, 400: OpenApiResponse(ErrorSerializer, description='validation_error')},
)
class TenantCreateView(generics.CreateAPIView):
    """Create a tenant and its API key. The key is shown only in this response.

    Public: no API key is needed, since this creates the tenant that later
    requests are scoped to.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = TenantSerializer
