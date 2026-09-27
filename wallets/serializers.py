from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Transaction, User, Wallet
from .services import BIGINT_MAX, create_user


@extend_schema_field(OpenApiTypes.INT)
class StrictAmountField(serializers.Field):
    """A positive integer amount in paisa.

    DRF's IntegerField accepts "100" and 100.0; this only takes a real JSON
    integer. bool is rejected too, although Python counts it as an int.
    """

    default_error_messages = {
        'invalid': 'Must be an integer number of paisa.',
        'min_value': 'Must be greater than 0.',
        'max_value': f'Must be at most {BIGINT_MAX}.',
    }

    def to_internal_value(self, data):
        if type(data) is not int:
            self.fail('invalid')
        if data < 1:
            self.fail('min_value')
        if data > BIGINT_MAX:
            self.fail('max_value')
        return data

    def to_representation(self, value):
        return value


class AmountSerializer(serializers.Serializer):
    amount = StrictAmountField(help_text='Paisa, greater than 0.')


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
