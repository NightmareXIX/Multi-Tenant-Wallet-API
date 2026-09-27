from rest_framework import serializers

from .models import Transaction, User, Wallet
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


class TransactionSerializer(serializers.ModelSerializer):
    # Read from the *_id columns, so listing a page never queries the wallets.
    source_wallet_id = serializers.UUIDField(read_only=True, allow_null=True, help_text='Null for deposits.')
    destination_wallet_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text='Null for withdrawals.'
    )

    class Meta:
        model = Transaction
        fields = [
            'id',
            'type',
            'amount',
            'source_wallet_id',
            'destination_wallet_id',
            'idempotency_key',
            'created_at',
        ]
        read_only_fields = fields
