from rest_framework import serializers

from .models import User, Wallet
from .services import create_user


class WalletSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Wallet
        fields = ['id', 'user_id', 'balance', 'created_at']
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    wallet = WalletSerializer(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'name', 'wallet', 'created_at']

    def create(self, validated_data):
        return create_user(self.context['request'].auth, **validated_data)
