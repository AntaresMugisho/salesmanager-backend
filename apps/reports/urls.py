from django.urls import path

from apps.reports.views import ResultReportView, SalesReportView

urlpatterns = [
    path("reports/result/", ResultReportView.as_view(), name="report-result"),
    path("reports/sales/", SalesReportView.as_view(), name="report-sales"),
]
