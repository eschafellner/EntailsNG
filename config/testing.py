"""Test runner that keeps uploads out of the checkout's media directories."""
import shutil
import tempfile
from pathlib import Path

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class IsolatedMediaTestRunner(DiscoverRunner):
    """Redirects MEDIA_ROOT and PRIVATE_MEDIA_ROOT to a temporary directory for the whole run.

    Tests that override these settings themselves keep their own directories.
    Parallel workers inherit the override when started via fork (Linux, CI, container).
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._media_dir = Path(tempfile.mkdtemp(prefix='entails-test-media-'))
        self._media_override = override_settings(
            MEDIA_ROOT=self._media_dir / 'media',
            PRIVATE_MEDIA_ROOT=self._media_dir / 'private_media',
        )
        self._media_override.enable()

    def teardown_test_environment(self, **kwargs):
        self._media_override.disable()
        shutil.rmtree(self._media_dir, ignore_errors=True)
        super().teardown_test_environment(**kwargs)
