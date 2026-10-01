from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache
from django.views.decorators.vary import vary_on_cookie


def require_staff(user):
    if not (user and user.is_authenticated and user.is_active and user.is_staff and not user.deleted_at):
        raise PermissionDenied


def staff_only(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        require_staff(request.user)
        return view(request, *args, **kwargs)
    return never_cache(vary_on_cookie(login_required(guarded)))
