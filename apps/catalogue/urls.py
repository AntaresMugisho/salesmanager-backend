from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalogue.views import ArticleViewSet, CategoryViewSet, SupplierViewSet

router = DefaultRouter()
router.register("categories", CategoryViewSet, basename="category")
router.register("suppliers", SupplierViewSet, basename="supplier")
router.register("articles", ArticleViewSet, basename="article")

urlpatterns = [path("", include(router.urls))]
