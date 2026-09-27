from django.urls import include, path

# Every route is defined without a trailing slash, e.g. /api/v1/tenants.
urlpatterns = [
    path('api/v1/', include('tenants.urls')),
    path('api/v1/', include('wallets.urls')),
]
