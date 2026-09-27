from django.urls import path

from .views import UserCreateView, WalletDetailView

urlpatterns = [
    path('users', UserCreateView.as_view(), name='user-create'),
    path('wallets/<uuid:wallet_id>', WalletDetailView.as_view(), name='wallet-detail'),
]
