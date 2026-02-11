"""Shared helpers for cancellation-password gating."""

from barkat.models import UserSettings


def user_has_cancellation_password(request):
    """True if the current user has a cancellation password set in UserSettings."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return False
    try:
        us = UserSettings.objects.get(user=request.user)
        return bool((getattr(us, "cancellation_password", None) or "").strip())
    except UserSettings.DoesNotExist:
        return False
