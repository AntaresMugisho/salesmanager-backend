from django.urls import path

from apps.reports.views import ResultReportView

urlpatterns = [
    path("reports/result/", ResultReportView.as_view(), name="report-result"),
]
