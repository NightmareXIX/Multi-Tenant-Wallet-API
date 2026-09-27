from drf_spectacular.utils import extend_schema
from rest_framework import generics

from .serializers import UserSerializer


@extend_schema(summary='Create a user and their wallet', tags=['Users'])
class UserCreateView(generics.CreateAPIView):
    """Create a user in the calling tenant, together with their one wallet (balance 0).

    Keep the returned `wallet.id`: every money route takes it.
    """

    serializer_class = UserSerializer
