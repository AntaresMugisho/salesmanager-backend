from django.utils.translation import gettext_lazy as _

from apps.common.exceptions import Conflict
from apps.common.views import CatalogueViewSet
from apps.sales.models import Customer
from apps.sales.serializers import CustomerSerializer


class CustomerViewSet(CatalogueViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    search_fields = ["name", "contact_name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def perform_destroy(self, instance):
        used = instance.sales.count()
        if used:
            raise Conflict(
                _(
                    "Ce client est lié à %(count)d vente%(plural)s et ne peut "
                    "pas être supprimé. Archivez-le à la place."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()
