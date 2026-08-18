from io import BytesIO
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from clans.models import Clan, ClanMembership

User = get_user_model()


class ClanModuleTests(TestCase):

    def setUp(self):
        self.user_a = User.objects.create_user(
            username='leader', email='leader@example.com', password='password'
        )
        self.user_b = User.objects.create_user(
            username='member1', email='member1@example.com', password='password'
        )
        self.user_c = User.objects.create_user(
            username='applicant', email='applicant@example.com', password='password'
        )

    def test_create_clan(self):
        self.client.login(username='leader', password='password')
        response = self.client.post(
            reverse('clan_create'),
            {
                'name': 'Fnatic',
                'website': 'https://fnatic.com',
                'password': 'secretpassword',
            },
        )
        self.assertTrue(Clan.objects.filter(name='Fnatic').exists())
        clan = Clan.objects.get(name='Fnatic')
        self.assertRedirects(response, reverse('clan_detail', kwargs={'slug': clan.slug}))
        self.assertTrue(clan.is_admin(self.user_a))
        self.assertTrue(clan.check_password('secretpassword'))
        self.assertFalse(clan.check_password('wrongpassword'))

    def test_edit_clan_optional_password(self):
        clan = Clan.objects.create(name='Fnatic')
        clan.set_password('originalpassword')
        clan.save()
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        self.client.login(username='leader', password='password')
        # Edit without providing a new password
        response = self.client.post(
            reverse('clan_edit', kwargs={'slug': clan.slug}),
            {
                'name': 'Fnatic Updated',
                'website': 'https://fnatic.com',
                'password': '',
            },
        )
        self.assertRedirects(response, reverse('clan_detail', kwargs={'slug': clan.slug}))
        clan.refresh_from_db()
        self.assertEqual(clan.name, 'Fnatic Updated')
        self.assertTrue(clan.check_password('originalpassword'))


    def test_logo_invalid_extension(self):
        clan = Clan.objects.create(name='TestClan', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        self.client.login(username='leader', password='password')
        bad_file = SimpleUploadedFile("logo.txt", b"not an image", content_type="text/plain")
        response = self.client.post(
            reverse('clan_edit', kwargs={'slug': clan.slug}),
            {
                'name': 'TestClan',
                'logo': bad_file,
            },
        )
        self.assertTrue(response.context['form'].has_error('logo'))

    def test_logo_valid_image(self):
        from PIL import Image
        import io
        img_io = io.BytesIO()
        img = Image.new('RGB', (200, 200), color='green')
        img.save(img_io, format='PNG')
        img_io.seek(0)
        valid_file = SimpleUploadedFile("valid_logo.png", img_io.getvalue(), content_type="image/png")

        clan = Clan.objects.create(name='ValidLogoClan', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        self.client.login(username='leader', password='password')
        response = self.client.post(
            reverse('clan_edit', kwargs={'slug': clan.slug}),
            {
                'name': 'ValidLogoClan',
                'logo': valid_file,
            },
        )
        self.assertRedirects(response, reverse('clan_detail', kwargs={'slug': clan.slug}))

    def test_logo_oversized_dimensions(self):
        from PIL import Image
        import io
        img_io = io.BytesIO()
        img = Image.new('RGB', (500, 500), color='red')
        img.save(img_io, format='PNG')
        img_io.seek(0)
        oversized_file = SimpleUploadedFile("huge_logo.png", img_io.getvalue(), content_type="image/png")

        clan = Clan.objects.create(name='HugeLogoClan', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        self.client.login(username='leader', password='password')
        response = self.client.post(
            reverse('clan_edit', kwargs={'slug': clan.slug}),
            {
                'name': 'HugeLogoClan',
                'logo': oversized_file,
            },
        )
        self.assertTrue(response.context['form'].has_error('logo'))



    def test_join_clan_via_password(self):
        clan = Clan.objects.create(name='SK Gaming')
        clan.set_password('skpass')
        clan.save()
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )

        self.client.login(username='member1', password='password')
        # Wrong password attempt
        bad_response = self.client.post(
            reverse('clan_join_password', kwargs={'slug': clan.slug}),
            {'password': 'wrongpass'},
        )
        self.assertRedirects(bad_response, reverse('clan_detail', kwargs={'slug': clan.slug}))
        self.assertFalse(ClanMembership.objects.filter(user=self.user_b, clan=clan).exists())

        # Correct password attempt
        response = self.client.post(
            reverse('clan_join_password', kwargs={'slug': clan.slug}),
            {'password': 'skpass'},
        )
        self.assertRedirects(response, reverse('clan_detail', kwargs={'slug': clan.slug}))
        membership = ClanMembership.objects.filter(user=self.user_b, clan=clan).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.status, ClanMembership.Status.ACCEPTED)


    def test_join_request_accept_and_reject(self):
        clan = Clan.objects.create(name='Natus Vincere', password='navipass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )

        # Applicant sends request
        self.client.login(username='applicant', password='password')
        self.client.post(reverse('clan_request_join', kwargs={'slug': clan.slug}))
        req_membership = ClanMembership.objects.filter(user=self.user_c, clan=clan).first()
        self.assertEqual(req_membership.status, ClanMembership.Status.PENDING)

        # Leader accepts request
        self.client.login(username='leader', password='password')
        self.client.post(
            reverse('clan_manage_request', kwargs={'slug': clan.slug, 'membership_id': req_membership.id}),
            {'action': 'accept'},
        )
        req_membership.refresh_from_db()
        self.assertEqual(req_membership.status, ClanMembership.Status.ACCEPTED)

    def test_leave_clan_auto_admin_promotion(self):
        clan = Clan.objects.create(name='Team Liquid', password='liquidpass')
        m_admin = ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        m_member = ClanMembership.objects.create(
            user=self.user_b, clan=clan, role=ClanMembership.Role.MEMBER, status=ClanMembership.Status.ACCEPTED
        )

        # Admin leaves
        self.client.login(username='leader', password='password')
        self.client.post(reverse('clan_leave', kwargs={'slug': clan.slug}))

        self.assertFalse(ClanMembership.objects.filter(user=self.user_a, clan=clan).exists())
        m_member.refresh_from_db()
        self.assertEqual(m_member.role, ClanMembership.Role.ADMIN)

    def test_clan_list_and_detail_views(self):
        clan = Clan.objects.create(name='Mousesports', password='mousespass')
        response = self.client.get(reverse('clan_list'))
        self.assertEqual(response.status_code, 200)

        response = self.client.get(reverse('clan_detail', kwargs={'slug': clan.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Mousesports')

    def test_clans_persist_across_event_switches(self):
        """Positiver Test: Clans bleiben nach einem Event-Wechsel dauerhaft in der Clanliste sichtbar."""
        from datetime import timedelta
        from django.utils import timezone
        from events.models import Event, EventRegistration

        event_2026 = Event.objects.create(
            title="Haag-networX 2026",
            slug="haag-2026",
            is_active=True,
            start_date=timezone.now() + timedelta(days=10),
            end_date=timezone.now() + timedelta(days=12),
        )
        event_2027 = Event.objects.create(
            title="Haag-networX 2027",
            slug="haag-2027",
            is_active=False,
            start_date=timezone.now() + timedelta(days=365),
            end_date=timezone.now() + timedelta(days=367),
        )

        clan = Clan.objects.create(name='Ninjas in Pyjamas', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        EventRegistration.objects.create(user=self.user_a, event=event_2026)

        # 1. Event 2026 ist aktiv -> Clan ist sichtbar
        res1 = self.client.get(reverse('clan_list'))
        self.assertEqual(res1.status_code, 200)
        self.assertContains(res1, 'Ninjas in Pyjamas')

        # 2. Event-Wechsel auf 2027 (User A hat sich für 2027 noch nicht angemeldet)
        event_2026.is_active = False
        event_2026.save()
        event_2027.is_active = True
        event_2027.save()

        # Clan muss trotzdem sichtbar bleiben!
        res2 = self.client.get(reverse('clan_list'))
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, 'Ninjas in Pyjamas')

    def test_clan_auto_deleted_when_last_member_leaves(self):
        """Positiver Test: Verlässt das letzte Mitglied den Clan, wird der Clan automatisch gelöscht."""
        clan = Clan.objects.create(name='Solo Clan', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        self.assertTrue(Clan.objects.filter(name='Solo Clan').exists())

        self.client.login(username='leader', password='password')
        response = self.client.post(reverse('clan_leave', kwargs={'slug': clan.slug}))
        self.assertRedirects(response, reverse('clan_list'))

        # Clan muss nun vollständig gelöscht sein
        self.assertFalse(Clan.objects.filter(name='Solo Clan').exists())
        self.assertFalse(ClanMembership.objects.filter(clan=clan).exists())

    def test_negative_clan_not_deleted_if_members_remain(self):
        """Negativer Test: Ein Clan darf NICHT gelöscht werden, wenn noch andere Mitglieder vorhanden sind."""
        clan = Clan.objects.create(name='Duo Clan', password='pass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )
        ClanMembership.objects.create(
            user=self.user_b, clan=clan, role=ClanMembership.Role.MEMBER, status=ClanMembership.Status.ACCEPTED
        )

        # Member B verlässt den Clan
        self.client.login(username='member1', password='password')
        response = self.client.post(reverse('clan_leave', kwargs={'slug': clan.slug}))
        self.assertRedirects(response, reverse('clan_list'))

        # Clan muss weiterhin existieren, da User A noch drin ist
        self.assertTrue(Clan.objects.filter(name='Duo Clan').exists())
        self.assertEqual(clan.memberships.filter(status=ClanMembership.Status.ACCEPTED).count(), 1)

    def test_clan_password_automatic_hashing_on_save(self):
        """Passwörter im Klartext werden bei save() automatisch gehasht und check_password validiert sicher."""
        clan = Clan.objects.create(name='Security Clan', password='plain_secret_123')
        clan.refresh_from_db()

        # Passwort darf in der DB nicht mehr im Klartext liegen
        self.assertNotEqual(clan.password, 'plain_secret_123')
        self.assertTrue(clan.password.startswith('pbkdf2_') or clan.password.startswith('argon2') or clan.password.startswith('bcrypt'))
        self.assertTrue(clan.check_password('plain_secret_123'))
        self.assertFalse(clan.check_password('wrong_secret'))

