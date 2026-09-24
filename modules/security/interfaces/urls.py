from django.urls import path

from modules.security.interfaces.audit_views import AuditLogView
from modules.security.interfaces.code_views import AccessCodeIssueView
from modules.security.interfaces.role_views import RoleDetailView, RoleListView
from modules.security.interfaces.views import (
    MyLanguageView,
    UserCreateView,
    UserDetailView,
    UserListView,
)

urlpatterns = [
    path("users/", UserListView.as_view(), name="users"),
    path("users/new/", UserCreateView.as_view(), name="user-create"),
    path("users/me/language/", MyLanguageView.as_view(), name="my-language"),
    path("users/<int:user_id>/", UserDetailView.as_view(), name="user-detail"),
    path(
        "users/<int:user_id>/access-code/",
        AccessCodeIssueView.as_view(),
        name="user-access-code",
    ),
    path("audit/", AuditLogView.as_view(), name="audit"),
    path("roles/", RoleListView.as_view(), name="roles"),
    path("roles/<int:role_id>/", RoleDetailView.as_view(), name="role-detail"),
]
