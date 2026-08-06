from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.sales.views import CustomerViewSet

router = DefaultRouter()
router.register("customers", CustomerViewSet, basename="customer")

urlpatterns = [path("", include(router.urls))]
