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

from django.contrib.auth.mixins import AccessMixin
from django.shortcuts import redirect
from django.contrib import messages

class GranularPermissionRequiredMixin(AccessMixin):
    """
    Mixin to enforce granular staff permissions.
    Set `required_permission` on the view class.
    """
    required_permission = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()

        if hasattr(request.user, "staff_profile"):
            # If the user is trying to access a read view, but they only have write access,
            # we STILL want to let them through to the generic view, so that we can render the "Create" button.
            # We will handle hiding the actual read data in the template or overriding get_context_data.
            
            # Let's see if we should allow them through.
            req_perm = self.required_permission
            has_perm = request.user.staff_profile.has_perm(req_perm)
            
            # If they don't have the specific read permission, check if they have the create permission for the same module.
            if not has_perm and req_perm and req_perm.endswith('_r'):
                create_perm = req_perm[:-2] + '_c'
                if request.user.staff_profile.has_perm(create_perm):
                    # They have create access but not read. Let them through, but flag it.
                    request._has_read_permission = False
                    return super().dispatch(request, *args, **kwargs)
                
            if not has_perm:
                messages.error(request, f"You do not have permission to access this page ({self.required_permission}).")
                return redirect("business")  # Redirect to a safe page
            else:
                request._has_read_permission = True
        else:
            # If they don't have a staff profile (e.g., standard admin), we might let them pass or deny
            if not request.user.is_superuser:
                messages.error(request, "Staff profile required to access this page.")
                return redirect("business")
            request._has_read_permission = True

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        # Fallback in case the view does not natively support get_context_data 
        # (e.g. it's a generic View without it, though most Django generic views do have it).
        if hasattr(super(), 'get_context_data'):
            ctx = super().get_context_data(**kwargs)
        else:
            ctx = {}
            
        ctx['has_read_permission'] = getattr(self.request, '_has_read_permission', True)
        return ctx
