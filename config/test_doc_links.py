import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

LINK = re.compile(r'\]\(([^)#\s]+)(?:#[^)]*)?\)')


class DocumentationLinkTests(SimpleTestCase):
    """F-002: Relative Verweise in Handover, README und docs/ zeigen auf vorhandene Dateien."""

    def test_relative_links_resolve(self):
        root = Path(settings.BASE_DIR)
        files = [root / 'DEVELOPER_HANDOVER.md', root / 'README.md', root / 'INSTRUCTIONS.MD', *sorted((root / 'docs').glob('*.md'))]
        broken = []
        for path in files:
            for target in LINK.findall(path.read_text(encoding='utf-8')):
                if re.match(r'^[a-z]+:', target):
                    continue
                if not (path.parent / target).exists():
                    broken.append(f'{path.relative_to(root)} -> {target}')
        self.assertEqual(broken, [])
