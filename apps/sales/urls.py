from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales.views import CustomerViewSet, SaleViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")
router.register("sales", SaleViewSet, basename="sale")

urlpatterns = [path("", include(router.urls))]
