import tempfile
from pathlib import Path

import django
from django.test import SimpleTestCase


class RequirementsPinCheckTests(SimpleTestCase):
    """F-001: start.sh erkennt eine venv, die von den Pins in requirements.txt abweicht."""

    def check(self, content):
        from scripts.check_requirements import mismatches
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'requirements.txt'
            path.write_text(content)
            return mismatches(path)

    def test_matching_pins_pass(self):
        self.assertEqual(self.check(f'# Kommentar\nDjango=={django.get_version()}\n\n'), [])

    def test_outdated_and_missing_packages_are_reported(self):
        result = self.check('Django==6.0.7\npsycopg[binary]==0.0.1\nnicht-installiertes-paket==1.0\n')
        self.assertEqual([name for name, _, _ in result], ['Django', 'psycopg', 'nicht-installiertes-paket'])
        self.assertEqual(result[0][1:], ('6.0.7', django.get_version()))
        self.assertIsNone(result[2][2])
