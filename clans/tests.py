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

    def test_edit_clan_optional_password(self):
        clan = Clan.objects.create(name='Fnatic', password='originalpassword')
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
        self.assertEqual(clan.password, 'originalpassword')

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
        self.assertFormError(response.context['form'], 'logo', "Ungültiges Format '.txt'. Bitte lade ein Bild im Format .jpg, .jpeg oder .png hoch.")

    def test_join_clan_via_password(self):
        clan = Clan.objects.create(name='SK Gaming', password='skpass')
        ClanMembership.objects.create(
            user=self.user_a, clan=clan, role=ClanMembership.Role.ADMIN, status=ClanMembership.Status.ACCEPTED
        )

        self.client.login(username='member1', password='password')
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
