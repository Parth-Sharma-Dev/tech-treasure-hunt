from django.contrib import admin
from django.urls import path

from .views import csrf, health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health, name="health"),
    path("api/auth/csrf", csrf, name="csrf"),
]
