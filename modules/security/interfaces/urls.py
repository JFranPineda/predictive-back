from django.urls import path

from modules.security.interfaces.views import MyLanguageView, UserDetailView, UserListView

urlpatterns = [
    path("users/", UserListView.as_view(), name="users"),
    path("users/me/language/", MyLanguageView.as_view(), name="my-language"),
    path("users/<int:user_id>/", UserDetailView.as_view(), name="user-detail"),
]
