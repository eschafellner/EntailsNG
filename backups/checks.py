from django.core.checks import Error, register
from .errors import BackupError
from .storage import validate_paths


@register()
def backup_paths_check(app_configs, **kwargs):
    try:
        validate_paths()
    except BackupError as exc:
        return [Error(str(exc), id='backups.E001')]
    return []
