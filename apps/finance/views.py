from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Site
from apps.common.dates import shop_timezone
from apps.common.permissions import IsManagerOrAbove
from apps.finance.aggregate import build_breakdown, bucketise, summarise
from apps.finance.facts import load_facts
from apps.finance.serializers import parse_range


class FinanceReadView(APIView):
    """Shared shape for the three reads.

    Manager and above: the README's role table puts « Dépenses, finances,
    rapports » out of a cashier's reach entirely.
    """

    permission_classes = [IsManagerOrAbove]

    #: Set by each subclass to one of the three aggregate functions.
    aggregate = None

    def get(self, request):
        start, end = parse_range(request.query_params)

        facts = load_facts(Site.objects.current())
        result = type(self).aggregate(facts, shop_timezone(), start, end)

        return Response(result)


class FinanceSummaryView(FinanceReadView):
    # staticmethod is not decoration for its own sake: a plain function
    # assigned to a class attribute becomes an instance method, so `self`
    # would arrive as the first argument.
    aggregate = staticmethod(summarise)


class FinanceSeriesView(FinanceReadView):
    aggregate = staticmethod(bucketise)


class FinanceBreakdownView(FinanceReadView):
    aggregate = staticmethod(build_breakdown)
