"""External listings and the boundaries with the existing tournament engine."""
from datetime import timedelta
from html import escape
from html.parser import HTMLParser
import re

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from configuration.models import SystemTranslation
from events.exceptions import EventLifecycleError
from events.models import Event, EventRegistration
from events.services import EventLifecycleService
from tournaments.forms import ExternalTournamentAdminForm
from tournaments.models import ExternalTournament, Game, Team, Tournament, TournamentRegistration
from tournaments.services import TournamentBracketService, TournamentRegistrationService
from users.models import User


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.links.append(dict(attrs))


@override_settings(SECURE_SSL_REDIRECT=False)
class ExternalTournamentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.staff = User.objects.create_user('external-orga', is_staff=True)
        cls.guest = User.objects.create_user('external-guest')
        cls.superuser = User.objects.create_superuser('external-admin', password='external-test-password')
        cls.event = Event.objects.create(
            title='External LAN', is_active=True, status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now + timedelta(days=2),
        )
        cls.other_event = Event.objects.create(
            title='Another LAN', status=Event.Status.REGISTRATION_OPEN,
            start_date=now, end_date=now + timedelta(days=2),
        )
        cls.game = Game.objects.create(name='Counter Strike 2', team_size=5)
        cls.public = ExternalTournament.objects.create(
            title='AlpenScene Cup', event=cls.event, game=cls.game, provider_name='alpenScene',
            external_url='https://alpenscene.pro/cup/2026?mode=cs2&source=lan#schedule',
            status=ExternalTournament.Status.PUBLISHED,
        )
        cls.draft = ExternalTournament.objects.create(
            title='External draft', event=cls.event, game=cls.game, provider_name='Draft provider',
            external_url='https://draft.example.com/cup',
        )

    def setUp(self):
        cache.clear()
        self.list_url = reverse('tournament_list')
        self.admin_list_url = reverse('admin:tournaments_externaltournament_changelist')
        self.admin_add_url = reverse('admin:tournaments_externaltournament_add')
        self.admin_change_url = reverse('admin:tournaments_externaltournament_change', args=[self.public.pk])

    def internal_tournament(self, **kwargs):
        now = timezone.now()
        data = dict(
            title='Internal Cup', event=self.event, game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=now - timedelta(hours=1), registration_end=now + timedelta(days=1),
        )
        data.update(kwargs)
        return Tournament.objects.create(**data)

    def card(self, response, tournament=None):
        tournament = tournament or self.public
        match = re.search(
            rf'data-external-tournament-id="{tournament.pk}">(.*?)\n</div>',
            response.content.decode(), re.S,
        )
        self.assertIsNotNone(match)
        return match.group(1)

    def admin_data(self, **changes):
        data = dict(
            event=self.event.pk, game=self.game.pk, title='New external Cup', provider_name='External provider',
            external_url='https://external.example.com/cup', status=ExternalTournament.Status.DRAFT,
            description='', mode='', tournament_start_0='', tournament_start_1='',
            registration_end_0='', registration_end_1='',
        )
        data.update(changes)
        return data

    def grant(self, user, *actions):
        user.user_permissions.add(*Permission.objects.filter(
            content_type__app_label='tournaments', content_type__model='externaltournament',
            codename__in=[f'{action}_externaltournament' for action in actions],
        ))

    def test_model_accepts_complete_https_links_with_paths_queries_and_ports(self):
        for url in (
            self.public.external_url, 'https://alpenscene.pro/',
            'https://staatscup.alpenscene.pro/cup/staatscup-1/',
            'https://provider.example.com:65535/cup?q=1&lang=de#playoffs',
            'https://bücher.example.com/turnier',
        ):
            with self.subTest(url=url):
                self.public.external_url = url
                self.public.save()
                self.assertEqual(self.public.safe_external_url, url)

    def test_model_rejects_unsafe_links_and_preserves_existing_address(self):
        original = self.public.external_url
        for url in (
            '', 'alpenscene.pro', '//alpenscene.pro/', 'http://alpenscene.pro/',
            'javascript:alert(1)', 'data:text/html,test', 'ftp://provider.example.com/cup',
            'https://user:pass@alpenscene.pro/cup', 'https://user@alpenscene.pro/cup',
            'https://alpenscene.pro/with space', 'https://alpenscene.pro/\nfoo',
            'https://alpenscene.pro/\x00foo', 'https://alpenscene.pro/\x7ffoo',
            'https://alpenscene.pro\\@evil.example.com/',
            'https://alpenscene.pro:65536/cup', 'https://alpenscene.pro:0/cup',
            'https://alpenscene.pro:abc/cup',
        ):
            with self.subTest(url=url):
                self.public.external_url = url
                with self.assertRaises(ValidationError):
                    self.public.save()
                self.assertEqual(ExternalTournament.objects.get(pk=self.public.pk).external_url, original)

    def test_required_information_and_publication_state_are_validated(self):
        for field, value in (('event', None), ('game', None), ('title', ''), ('provider_name', ''), ('status', 'OPEN')):
            with self.subTest(field=field):
                item = ExternalTournament.objects.get(pk=self.public.pk)
                setattr(item, field, value)
                with self.assertRaises(ValidationError):
                    item.full_clean()

    def test_external_cards_are_available_to_guests_without_ticket_or_checkin(self):
        for actor in (None, self.guest):
            self.client.force_login(actor) if actor else self.client.logout()
            response = self.client.get(self.list_url)
            self.assertContains(response, self.public.title)
            self.assertNotContains(response, self.draft.title)
            self.assertNotContains(response, 'Aktuell sind keine Turniere')
            card = self.card(response)
            self.assertIn('Extern', card)
            self.assertIn('5v5 Team', card)
            self.assertIn('Anbieter: alpenScene', card)
            links = Links(card).links
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]['href'], self.public.external_url)
            self.assertNotIn('target', links[0])
        self.assertFalse(EventRegistration.objects.filter(user=self.guest).exists())
        self.assertFalse(TournamentRegistration.objects.exists())

    def test_active_staff_and_superusers_see_drafts_without_internal_publication_form(self):
        for actor in (self.staff, self.superuser):
            self.client.force_login(actor)
            response = self.client.get(self.list_url)
            self.assertContains(response, self.draft.title)
            card = self.card(response, self.draft)
            self.assertIn('Entwurf', card)
            self.assertNotIn('<form', card)
            self.assertNotIn('/open-registration/', card)

    def test_inactive_or_deleted_staff_do_not_gain_draft_visibility(self):
        inactive = User.objects.create_user('external-inactive', is_staff=True, is_active=False)
        deleted = User.objects.create_user('external-deleted', is_staff=True)
        deleted.deleted_at = timezone.now()
        for actor in (AnonymousUser(), self.guest, inactive, deleted):
            with self.subTest(actor=str(actor)):
                self.assertEqual(list(ExternalTournament.objects.visible_to(actor)), [self.public])

    def test_visibility_is_filtered_for_each_request(self):
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(self.list_url), self.draft.title)
        self.client.logout()
        self.assertNotContains(self.client.get(self.list_url), self.draft.title)
        self.client.force_login(self.guest)
        self.assertNotContains(self.client.get(self.list_url), self.draft.title)

    def test_only_listings_from_the_active_event_are_shown(self):
        self.public.event = self.other_event
        self.public.save()
        response = self.client.get(self.list_url)
        self.assertNotContains(response, self.public.title)
        self.assertContains(response, 'Aktuell sind keine Turniere')
        self.other_event.is_active = True
        self.other_event.save()
        self.assertContains(self.client.get(self.list_url), self.public.title)

    def test_no_active_event_and_draft_only_lists_show_empty_state(self):
        self.public.status = ExternalTournament.Status.DRAFT
        self.public.save()
        self.assertContains(self.client.get(self.list_url), 'Aktuell sind keine Turniere')
        self.client.force_login(self.staff)
        self.assertNotContains(self.client.get(self.list_url), 'Aktuell sind keine Turniere')
        self.event.is_active = False
        self.event.save()
        response = self.client.get(self.list_url)
        self.assertContains(response, 'Aktuell sind keine Turniere')
        self.assertNotContains(response, self.public.title)
        self.assertNotContains(response, self.draft.title)

    def test_optional_metadata_is_shown_only_when_present(self):
        card = self.card(self.client.get(self.list_url))
        self.assertNotIn('Anmeldeschluss:', card)
        self.assertNotIn('Turnierstart:', card)
        self.assertNotIn('Angemeldete Teams', card)
        self.public.mode = 'Schweizer System'
        self.public.description = 'Anmeldung direkt beim Veranstalter.'
        self.public.registration_end = timezone.now() + timedelta(days=1)
        self.public.tournament_start = timezone.now() + timedelta(days=2)
        self.public.save()
        card = self.card(self.client.get(self.list_url))
        self.assertIn(self.public.mode, card)
        self.assertIn(self.public.description, card)
        self.assertIn('Anmeldeschluss:', card)
        self.assertIn('Turnierstart:', card)
        self.assertIn(timezone.localtime(self.public.tournament_start).strftime('%d.%m.%Y %H:%M'), card)

    def test_untrusted_listing_text_is_escaped(self):
        self.public.title = '<script>alert("title")</script>'
        self.public.provider_name = '<img src=x onerror=alert(1)>'
        self.public.description = '<a href="javascript:alert(1)">unsafe</a>\nSecond line'
        self.public.mode = '<iframe src="https://evil.example.com"></iframe>'
        self.public.save()
        card = self.card(self.client.get(self.list_url))
        for text in (self.public.title, self.public.provider_name, self.public.mode):
            self.assertIn(escape(text), card)
        self.assertNotIn('<script', card)
        self.assertNotIn('<iframe', card)
        self.assertEqual(len(Links(card).links), 1)

    def test_invalid_links_imported_without_validation_are_never_rendered_as_links(self):
        for url in ('javascript:alert(1)', 'http://provider.example.com/', 'https://user:secret@provider.example.com/'):
            with self.subTest(url=url):
                ExternalTournament.objects.filter(pk=self.public.pk).update(external_url=url)
                card = self.card(self.client.get(self.list_url))
                self.assertEqual(Links(card).links, [])
                self.assertIn('Link derzeit nicht verfügbar.', card)

    def test_translations_can_be_customized(self):
        SystemTranslation.objects.update_or_create(key='external_tournament_open', defaults={'text': 'Beim Anbieter öffnen'})
        cache.clear()
        self.assertContains(self.client.get(self.list_url), 'Beim Anbieter öffnen')

    def test_mixed_overview_preserves_internal_order_and_links(self):
        first = self.internal_tournament(title='First internal')
        second = self.internal_tournament(title='Second internal', registration_start=timezone.now())
        self.public.status = ExternalTournament.Status.DRAFT
        self.public.save()
        original_order = list(self.client.get(self.list_url).context['tournaments'])
        self.public.status = ExternalTournament.Status.PUBLISHED
        self.public.save()
        response = self.client.get(self.list_url)
        self.assertEqual(list(response.context['tournaments']), original_order)
        html = response.content.decode()
        self.assertLess(html.index(original_order[0].title), html.index(original_order[1].title))
        self.assertLess(html.index(first.title), html.index(self.public.title))
        self.assertLess(html.index(second.title), html.index(self.public.title))
        self.assertContains(response, reverse('tournament_detail', args=[first.slug]))
        self.assertContains(response, 'Jetzt anmelden')
        self.assertNotContains(response, 'Aktuell sind keine Turniere')

    def test_colliding_ids_do_not_show_internal_registration_status_on_external_card(self):
        solo = Game.objects.create(name='Internal solo', team_size=1)
        internal = self.internal_tournament(pk=self.public.pk, game=solo)
        TournamentRegistrationService.register_team(internal.pk, user=self.guest, actor=self.staff)
        self.client.force_login(self.guest)
        response = self.client.get(self.list_url)
        self.assertEqual(response.context['registered_tournament_ids'], {internal.pk})
        self.assertContains(response, 'Angemeldet')
        card = self.card(response)
        self.assertNotIn('Angemeldet', card)
        self.assertNotIn('Zum Spielplan', card)
        self.assertIn('Zum Turnier', card)

    def test_existing_internal_detail_and_registration_still_work(self):
        solo = Game.objects.create(name='Solo with external listing', team_size=1)
        internal = self.internal_tournament(game=solo)
        EventRegistration.objects.create(user=self.guest, event=self.event, is_checked_in=True)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(reverse('tournament_detail', args=[internal.slug])).status_code, 200)
        response = self.client.post(reverse('tournament_register', args=[internal.slug]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TournamentRegistration.objects.filter(tournament=internal, team__captain=self.guest).exists())
        self.public.refresh_from_db()
        self.assertEqual(self.public.status, ExternalTournament.Status.PUBLISHED)

    def test_existing_internal_bracket_generation_ignores_external_listings(self):
        solo = Game.objects.create(name='Solo bracket with external listing', team_size=1)
        internal = self.internal_tournament(game=solo)
        for index in range(2):
            player = User.objects.create_user(f'external-bracket-player-{index}')
            TournamentRegistrationService.register_team(internal.pk, user=player, actor=self.staff)
        TournamentBracketService.generate_bracket(internal.pk, actor=self.staff)
        internal.refresh_from_db()
        self.assertTrue(internal.is_generated)
        self.assertTrue(internal.matches.exists())
        self.assertEqual(ExternalTournament.objects.count(), 2)

    def test_external_listings_do_not_block_event_finish_or_create_tournament_data(self):
        finished, _ = EventLifecycleService.finish_event(self.event.pk)
        self.assertEqual(finished.status, Event.Status.FINISHED)
        self.assertFalse(Tournament.objects.exists())
        self.assertFalse(TournamentRegistration.objects.exists())
        self.assertFalse(Team.objects.exists())
        self.public.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.public.status, ExternalTournament.Status.PUBLISHED)
        self.assertEqual(self.draft.status, ExternalTournament.Status.DRAFT)

    def test_unfinished_internal_tournaments_still_block_event_finish(self):
        internal = self.internal_tournament()
        with self.assertRaises(EventLifecycleError):
            EventLifecycleService.finish_event(self.event.pk)
        internal.status = Tournament.Status.CANCELLED
        internal.save()
        self.assertEqual(EventLifecycleService.finish_event(self.event.pk)[0].status, Event.Status.FINISHED)

    def test_admin_form_validates_urls_and_allows_missing_optional_information(self):
        form = ExternalTournamentAdminForm(data=self.admin_data())
        self.assertTrue(form.is_valid(), form.errors)
        for url in ('http://alpenscene.pro/', 'https://user:pass@alpenscene.pro/', 'javascript:alert(1)'):
            form = ExternalTournamentAdminForm(data=self.admin_data(external_url=url))
            self.assertFalse(form.is_valid())
            self.assertIn('external_url', form.errors)

    def test_admin_requires_staff_and_specific_model_permissions(self):
        for actor in (None, self.guest, self.staff):
            self.client.force_login(actor) if actor else self.client.logout()
            for url in (self.admin_list_url, self.admin_add_url, self.admin_change_url):
                with self.subTest(actor=actor, url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403 if actor == self.staff else 302)
        self.grant(self.staff, 'view')
        self.assertEqual(self.client.get(self.admin_list_url).status_code, 200)
        self.assertEqual(self.client.get(self.admin_change_url).status_code, 200)
        self.assertEqual(self.client.get(self.admin_add_url).status_code, 403)
        self.assertEqual(self.client.post(self.admin_change_url, self.admin_data(status='PUBLISHED')).status_code, 403)

    def test_authorized_admin_can_create_publish_edit_and_hide_listing(self):
        self.grant(self.staff, 'view', 'add', 'change')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(self.admin_add_url, self.admin_data()).status_code, 302)
        item = ExternalTournament.objects.get(title='New external Cup')
        change_url = reverse('admin:tournaments_externaltournament_change', args=[item.pk])
        self.client.logout()
        self.assertNotContains(self.client.get(self.list_url), item.title)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(change_url, self.admin_data(status='PUBLISHED', title='Published Cup')).status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get(self.list_url), 'Published Cup')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(change_url, self.admin_data(status='DRAFT', title='Published Cup')).status_code, 302)
        self.client.logout()
        self.assertNotContains(self.client.get(self.list_url), 'Published Cup')

    def test_admin_rejects_invalid_link_without_creating_a_listing(self):
        self.client.force_login(self.superuser)
        response = self.client.post(self.admin_add_url, self.admin_data(external_url='http://alpenscene.pro/'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('external_url', response.context['adminform'].form.errors)
        self.assertEqual(ExternalTournament.objects.count(), 2)

    def test_admin_publication_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.superuser)
        self.assertEqual(client.post(self.admin_change_url, self.admin_data(status='PUBLISHED')).status_code, 403)

    def test_external_admin_has_no_internal_engine_actions(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.admin_change_url)
        self.assertContains(response, 'Turnieradresse')
        self.assertNotContains(response, 'Neustart vorbereiten')
        self.assertNotContains(response, 'Ergebnisse verwalten')
        self.assertEqual(response.context['inline_admin_formsets'], [])
        self.assertEqual(admin.site._registry[ExternalTournament].inlines, ())
