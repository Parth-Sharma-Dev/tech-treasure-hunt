from django.contrib import admin
from django.urls import path

from competition import coding_views, gameplay_views, results_views, views

from .views import csrf, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health, name="health"),
    path("api/auth/csrf", csrf, name="csrf"),
    path("api/auth/login", views.team_login),
    path("api/auth/logout", views.team_logout),
    path("api/me", views.me),
    path("api/rounds", views.portal_dashboard),
    path("api/rounds/<int:round_id>/overview", views.portal_overview),
    path("api/rounds/<int:round_id>/coding/submission", coding_views.submission),
    path("api/rounds/<int:round_id>/coding/tasks/<int:task_id>/response", coding_views.response),
    path("api/rounds/<int:round_id>/coding/finalize", coding_views.final),
    path("api/staff/rounds/<int:round_id>/coding/workstation", coding_views.station),
    path("api/practice", views.practice),
    path("api/practice/submit", views.submit_practice),
    path("api/missions/open", gameplay_views.open),
    path("api/missions/<str:token>", gameplay_views.mission),
    path("api/missions/<str:token>/submit", gameplay_views.submit),
    path("api/rounds/<int:round_id>/state", gameplay_views.state),
    path("api/rounds/<int:round_id>/attempts/<str:key>", gameplay_views.attempt),
    path("api/me/receipts", gameplay_views.receipts),
    path("api/rounds/<int:round_id>/results", results_views.published_results),
    path("api/staff/results", results_views.staff_result_rounds),
    path("api/staff/rounds/<int:round_id>/results", results_views.staff_preview),
    path("api/staff/rounds/<int:round_id>/publish", results_views.publish),
    path("api/staff/rounds/<int:round_id>/incidents", results_views.incident),
    path("api/staff/rounds/<int:round_id>/resolutions", results_views.resolutions),
    path("api/staff/rounds/<int:round_id>/paper", results_views.paper_action),
    path("api/staff/rounds/<int:round_id>/exports/<str:kind>", results_views.export_evidence),
    path("api/staff/rounds/<int:round_id>/recovery", results_views.recover_evidence),
    path("api/staff/rounds/<int:round_id>/receipts/verify", results_views.check_receipts),
    path("api/staff/rounds", views.staff_rounds),
    path("api/staff/rounds/<int:round_id>/control", views.staff_control_round),
    path(
        "api/staff/teams/<int:team_id>/sessions/<int:session_id>/revoke", views.staff_revoke_session
    ),
]
