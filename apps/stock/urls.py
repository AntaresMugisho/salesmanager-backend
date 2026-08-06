from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.stock.views import MovementViewSet

router = DefaultRouter()
router.register("stock/movements", MovementViewSet, basename="movement")

urlpatterns = [path("", include(router.urls))]
