"""Signing in with e-mail and password.

Kept apart from `authentication.py`: DRF imports that module while it loads
its own settings, and the token views import those settings back.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class MemberTokenSerializer(TokenObtainPairSerializer):
    """A correct password is not enough: the person must still belong to a
    company here. Without this, someone whose access was removed signed in
    to an empty screen."""

    def validate(self, attrs):
        data = super().validate(attrs)
        from modules.security.infrastructure.models import Membership

        if not self.user.is_superuser and not Membership.objects.filter(user=self.user).exists():
            # 403, not 401: the password was right, and the screen says why.
            raise PermissionDenied("Tu acceso a esta empresa fue retirado. Habla con el administrador.")
        return data


class LoginView(TokenObtainPairView):
    serializer_class = MemberTokenSerializer
