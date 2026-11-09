from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied


def user_has_capability(user, capability, property_obj=None):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    global_match = user.groups.filter(
        pms_profile__is_active=True,
        pms_capabilities__name=capability,
    ).exists()
    if global_match:
        return True
    if property_obj is None:
        return False
    return user.property_access.filter(
        property=property_obj,
        group__pms_profile__is_active=True,
        group__pms_capabilities__name=capability,
    ).exists()


def capability_required(capability):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user_has_capability(request.user, capability):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def properties_for_user(user, capability="properties.view"):
    from properties.models import Property

    if user.is_superuser or user.groups.filter(pms_profile__is_active=True, pms_capabilities__name=capability).exists():
        return Property.objects.all()
    return Property.objects.filter(
        staff_access__user=user,
        staff_access__group__pms_profile__is_active=True,
        staff_access__group__pms_capabilities__name=capability,
    ).distinct()
