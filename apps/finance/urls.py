from django.urls import path

from apps.finance.views import (
    FinanceBreakdownView,
    FinanceSeriesView,
    FinanceSummaryView,
)

urlpatterns = [
    path("finance/summary/", FinanceSummaryView.as_view(), name="finance-summary"),
    path("finance/series/", FinanceSeriesView.as_view(), name="finance-series"),
    path(
        "finance/breakdown/",
        FinanceBreakdownView.as_view(),
        name="finance-breakdown",
    ),
]
