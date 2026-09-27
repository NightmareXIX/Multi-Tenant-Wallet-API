from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# Every route is defined without a trailing slash, e.g. /api/v1/tenants.
urlpatterns = [
    path('api/schema', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/v1/', include('tenants.urls')),
    path('api/v1/', include('wallets.urls')),
]

# JSON bodies for errors raised outside DRF views, e.g. a malformed wallet id.
handler404 = 'wallets.exceptions.not_found'
handler500 = 'wallets.exceptions.server_error'
