from pathlib import Path
from django.conf import settings
from django.core.checks import Error, register


@register()
def private_storage_check(app_configs, **kwargs):
    private = Path(settings.PRIVATE_MEDIA_ROOT).resolve()
    public = [Path(settings.MEDIA_ROOT).resolve(), Path(settings.STATIC_ROOT).resolve()]
    public.extend(Path(root).resolve() for root in settings.STATICFILES_DIRS)
    if any(private == root or private.is_relative_to(root) for root in public):
        return [Error('PRIVATE_MEDIA_ROOT muss außerhalb der öffentlichen Medien- und Static-Verzeichnisse liegen.', id='knowledge.E001')]
    return []
