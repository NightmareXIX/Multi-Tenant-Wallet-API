from rest_framework import status
from rest_framework.exceptions import APIException

# Each default_code is the stable error code the Route Design lists for it.


class IdempotencyKeyMissing(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'idempotency_key_missing'
    default_detail = 'Send an Idempotency-Key header of 1 to 255 characters.'


class SameWalletTransfer(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = 'same_wallet_transfer'
    default_detail = 'The source and destination wallets must be different.'


class InsufficientFunds(APIException):
    # 422, not 400: the request is well-formed but fails on the wallet's current state.
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = 'insufficient_funds'
    default_detail = 'Wallet balance is lower than the requested amount.'


class IdempotencyKeyMismatch(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_code = 'idempotency_key_mismatch'
    default_detail = 'This Idempotency-Key was already used for a different request.'
