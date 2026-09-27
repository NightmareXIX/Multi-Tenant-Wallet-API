from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    ValidationError,
)
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler as drf_exception_handler

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


def error_body(code, message, fields=None):
    """The one shape every error leaves the API in."""
    error = {'code': code, 'message': message}
    if fields is not None:
        error['fields'] = fields
    return {'error': error}


def exception_handler(exc, context):
    """DRF's handler, with the body rewritten into the error shape.

    Only response.data is replaced, so headers DRF sets (WWW-Authenticate on 401) survive.
    """
    if isinstance(exc, Http404):
        # One message for a missing wallet and another tenant's, so nothing leaks.
        exc = NotFound()
    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, ValidationError):
        fields = exc.detail
        if not isinstance(fields, dict):
            fields = {api_settings.NON_FIELD_ERRORS_KEY: fields}
        response.data = error_body('validation_error', 'The request has invalid fields.', fields)
    elif isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        response.data = error_body('invalid_api_key', str(exc.detail))
    else:
        response.data = error_body(exc.get_codes(), str(exc.detail))
    return response
