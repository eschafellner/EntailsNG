import shutil
import tempfile
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Clan, ClanMembership

User = get_user_model()


def png(name='logo.png'):
    buffer = BytesIO()
    Image.new('RGB', (10, 10), 'red').save(buffer, format='PNG')
    return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')


class ClanCreateRaceTests(TestCase):
    """F-027 (1): Zweiter paralleler Request endet mit Meldung statt IntegrityError/HTTP 500."""

    def test_membership_created_after_first_check(self):
        user = User.objects.create_user('race-user', 'race@example.com', 'StrongPass123!')
        other = Clan.objects.create(name='Schon da', tag='SD', password='Geheim123!xy')
        ClanMembership.objects.create(user=user, clan=other, role=ClanMembership.Role.ADMIN,
                                      status=ClanMembership.Status.ACCEPTED)
        client = Client(raise_request_exception=False)
        client.force_login(user)
        # Die Vorabprüfung sieht die (parallel entstandene) Mitgliedschaft noch nicht.
        with patch.object(ClanMembership, 'get_user_active_membership', return_value=None):
            response = client.post(reverse('clan_create'), {
                'name': 'Neuer Clan', 'tag': 'NC', 'website': '', 'password': 'Geheim123!xy',
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Clan.objects.filter(name='Neuer Clan').exists())


class ClanAdminMemberCountTests(TestCase):
    """F-027 (2): Mitgliederzahl in der Admin-Liste ohne Abfrage pro Zeile."""

    def test_changelist_queries_do_not_grow_with_clans(self):
        admin_user = User.objects.create_superuser('clan-admin', 'clan-admin@example.com', 'password')
        self.client.force_login(admin_user)
        url = reverse('admin:clans_clan_changelist')

        def make(count, offset):
            for i in range(count):
                clan = Clan.objects.create(name=f'Clan {offset + i}', password='Geheim123!xy')
                ClanMembership.objects.create(user=User.objects.create_user(f'm{offset + i}'), clan=clan,
                                              status=ClanMembership.Status.ACCEPTED)

        make(2, 0)
        self.client.get(url)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as few:
            self.client.get(url)
        make(5, 10)
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(url)
        self.assertEqual(len(many), len(few))
        self.assertContains(response, 'Clan 14')


class ClanLogoReplacementTests(TestCase):
    """F-027 (3): Beim Ersetzen des Logos wird die alte Datei nach dem Commit gelöscht."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def test_old_logo_removed_after_commit(self):
        clan = Clan.objects.create(name='Logo Clan', password='Geheim123!xy', logo=png('alt.png'))
        old_name = clan.logo.name
        storage = clan.logo.storage
        self.assertTrue(storage.exists(old_name))
        with self.captureOnCommitCallbacks(execute=True):
            clan.logo = png('neu.png')
            clan.save()
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(clan.logo.name))
        with self.captureOnCommitCallbacks(execute=True):
            clan.name = 'Logo Clan 2'
            clan.save()
        self.assertTrue(storage.exists(clan.logo.name))
