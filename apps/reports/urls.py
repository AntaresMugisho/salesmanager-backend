from django.urls import path

from apps.reports.views import (
    ProfitabilityReportView,
    ResultReportView,
    SalesReportView,
    StockReportView,
)

urlpatterns = [
    path("reports/result/", ResultReportView.as_view(), name="report-result"),
    path("reports/sales/", SalesReportView.as_view(), name="report-sales"),
    path(
        "reports/profitability/",
        ProfitabilityReportView.as_view(),
        name="report-profitability",
    ),
    path("reports/stock/", StockReportView.as_view(), name="report-stock"),
]
