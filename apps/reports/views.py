from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Site
from apps.common.dates import shop_timezone
from apps.common.permissions import IsManagerOrAbove
from apps.finance.facts import load_facts
from apps.finance.serializers import parse_range
from apps.reports.result import build_result_report


class ReportReadView(APIView):
    """Shared shape for the four report reads.

    Manager and above: the README's role table puts « Dépenses, finances,
    rapports » out of a cashier's reach entirely.

    `generated_at` is stamped here rather than in a builder so the printed
    « Édité le » belongs to the response.
    """

    permission_classes = [IsManagerOrAbove]

    def get(self, request):
        start, end = parse_range(request.query_params)
        return Response(
            self.build(
                Site.objects.current(),
                shop_timezone(),
                start,
                end,
                timezone.now(),
            )
        )

    def build(self, site, tz, start, end, generated_at) -> dict:
        raise NotImplementedError


class ResultReportView(ReportReadView):
    def build(self, site, tz, start, end, generated_at) -> dict:
        return build_result_report(load_facts(site), tz, start, end, generated_at)
