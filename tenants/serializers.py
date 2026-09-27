from rest_framework import serializers

from .authentication import generate_api_key, hash_api_key
from .models import Tenant


class TenantSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(
        read_only=True,
        help_text='Shown only in this response. Send it as X-API-Key on every other request.',
    )

    class Meta:
        model = Tenant
        fields = ['id', 'name', 'api_key', 'created_at']

    def create(self, validated_data):
        key = generate_api_key()
        tenant = Tenant.objects.create(api_key_hash=hash_api_key(key), **validated_data)
        # Kept on the instance only for this response; the plain key is never stored.
        tenant.api_key = key
        return tenant
