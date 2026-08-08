from apps.accounts.models import Site
from apps.common.permissions import IsManagerOrAbove
from apps.common.views import CatalogueViewSet
from apps.expenses.filters import ExpenseFilterSet
from apps.expenses.models import Expense
from apps.expenses.serializers import ExpenseSerializer


class ExpenseViewSet(CatalogueViewSet):
    """Manager and above for *every* action, reads included.

    Not the catalogue map, where a cashier may read: the README's role table
    puts « Dépenses, finances, rapports » at manager and above outright, so
    `default_permission` is overridden rather than only the write actions.
    """

    queryset = Expense.objects.all()
    serializer_class = ExpenseSerializer
    filterset_class = ExpenseFilterSet
    search_fields = ["label", "reference", "note"]
    ordering_fields = ["spent_at", "amount", "created_at"]
    ordering = ["-spent_at"]

    default_permission = IsManagerOrAbove
    # Every action falls to the default; nothing is owner-only here. An
    # expense is deletable by any manager because nothing references it.
    permission_map = {}

    def perform_create(self, serializer):
        serializer.save(
            site=Site.objects.current(),
            user=self.request.user,
            user_name=self.request.user.full_name,
        )
