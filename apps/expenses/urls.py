from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.expenses.views import ExpenseViewSet

router = DefaultRouter()
router.register("expenses", ExpenseViewSet, basename="expense")

urlpatterns = [path("", include(router.urls))]
