from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.stock.views import DashboardView, LowStockView, MovementViewSet

router = DefaultRouter()
router.register("stock/movements", MovementViewSet, basename="movement")

# The explicit paths precede the router: its detail route would otherwise
# shadow them.
urlpatterns = [
    path("stock/low-stock/", LowStockView.as_view(), name="low-stock"),
    path("stock/dashboard/", DashboardView.as_view(), name="dashboard"),
    path("", include(router.urls)),
]
