import uuid
import os
from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.PRIVATE_MEDIA_ROOT

    @property
    def location(self):
        return os.path.abspath(self.base_location)

    def url(self, name):
        raise ValueError('Interne Dateien haben keine öffentliche Medien-URL.')


def private_storage():
    return PrivateStorage()


def attachment_path(instance, filename):
    return f'knowledge/{instance.page_id}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}'
