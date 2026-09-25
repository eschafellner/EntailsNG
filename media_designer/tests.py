from datetime import timedelta
from io import BytesIO
import re
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.models import Event, EventRegistration
from media_designer.data import certificate_rows
from media_designer.models import MediaTemplate
from media_designer.rendering import render_pdf, sheet_layout
from media_designer.schema import default_elements
from tournaments.models import (
    Game, Team, Tournament, TournamentMatch, TournamentMatchParticipant,
    TournamentRegistration,
)
from users.models import User


class MediaDesignerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.event = Event.objects.create(
            title='Export LAN', slug='export-lan', start_date=now,
            end_date=now + timedelta(days=2),
        )
        cls.other_event = Event.objects.create(
            title='Other LAN', slug='other-lan', start_date=now,
            end_date=now + timedelta(days=2),
        )
        cls.staff = User.objects.create_user(username='export-staff', is_staff=True)
        cls.guest = User.objects.create_user(username='export-guest')
        cls.other_guest = User.objects.create_user(username='other-guest')
        cls.registration = EventRegistration.objects.create(user=cls.guest, event=cls.event)
        cls.other_registration = EventRegistration.objects.create(user=cls.other_guest, event=cls.other_event)
        cls.badge = MediaTemplate.objects.create(
            event=cls.event, name='Badge', kind=MediaTemplate.Kind.BADGE,
            paper_size='A8', elements=default_elements('BADGE'), created_by=cls.staff,
        )

    def test_badge_sheet_has_nine_cards_and_real_a4_page_size(self):
        self.assertEqual(sheet_layout('A8'), (3, 3, 9))
        rows = [{'guest.username': f'Gast {index}', 'guest.seat': 'A-12'} for index in range(10)]
        pdf_file = render_pdf(self.badge, rows, on_a4=True)
        try:
            pdf = pdf_file.read()
        finally:
            pdf_file.close()
        self.assertTrue(pdf.startswith(b'%PDF-'))
        self.assertIn(b'/Count 2', pdf)
        media_boxes = re.findall(rb'/MediaBox \[ [^]]+ \]', pdf)
        self.assertTrue(media_boxes)
        self.assertTrue(all(box == b'/MediaBox [ 0 0 595.2 841.92 ]' for box in media_boxes))

    def test_invalid_fields_are_rejected_before_rendering(self):
        self.badge.elements = [{**default_elements('BADGE')[0], 'source': 'guest.email'}]
        with self.assertRaises(ValidationError):
            self.badge.full_clean()
        with self.assertRaises(ValidationError):
            render_pdf(self.badge, [{'guest.email': 'private@example.test'}])

    def test_background_only_template_can_be_saved(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('media_template_edit', args=[self.badge.pk]), {
            'event': self.event.pk, 'name': 'Background only',
            'paper_size': 'A8', 'elements': '[]',
        })
        self.assertEqual(response.status_code, 302)
        self.badge.refresh_from_db()
        self.assertEqual(self.badge.elements, [])

    def test_create_editor_and_export_require_staff(self):
        url = reverse('media_template_list')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.guest)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(reverse('media_template_export', args=[self.badge.pk])).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('media_template_edit', args=[self.badge.pk])).status_code, 200)

    def test_create_rejects_certificate_in_badge_size(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('media_template_create'), {
            'event': self.event.pk, 'name': 'Invalid',
            'kind': MediaTemplate.Kind.CERTIFICATE, 'paper_size': 'A8',
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MediaTemplate.objects.filter(name='Invalid').exists())

    def test_uploaded_background_is_saved_and_used_for_export(self):
        image = Image.new('RGB', (520, 740), '#345678')
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        upload = SimpleUploadedFile('background.png', buffer.getvalue(), content_type='image/png')
        self.client.force_login(self.staff)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse('media_template_create'), {
                'event': self.event.pk, 'name': 'With background',
                'kind': MediaTemplate.Kind.BADGE, 'paper_size': 'A8',
                'background': upload,
            })
            self.assertEqual(response.status_code, 302)
            template = MediaTemplate.objects.get(name='With background')
            self.assertTrue(template.background.name.endswith('background.png'))
            pdf = render_pdf(template, [{'guest.username': 'Test'}])
            try:
                self.assertTrue(pdf.read().startswith(b'%PDF-'))
            finally:
                pdf.close()
            response = self.client.post(reverse('media_template_edit', args=[template.pk]), {
                'event': self.event.pk, 'name': 'With background edited',
                'paper_size': 'A8', 'elements': '[]',
            })
            self.assertEqual(response.status_code, 302)

    def test_corrupt_background_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse('media_template_create'), {
            'event': self.event.pk, 'name': 'Bad image',
            'kind': MediaTemplate.Kind.BADGE, 'paper_size': 'A8',
            'background': SimpleUploadedFile('bad.png', b'not an image', content_type='image/png'),
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(MediaTemplate.objects.filter(name='Bad image').exists())

    def test_export_only_accepts_registrations_from_template_event(self):
        self.client.force_login(self.staff)
        url = reverse('media_template_export', args=[self.badge.pk])
        response = self.client.post(url, {
            'recipients': [str(self.registration.pk), str(self.other_registration.pk)],
            'sheet': 'a4',
        })
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response['Content-Type'], 'application/pdf')

        response = self.client.post(url, {
            'recipients': [str(self.registration.pk)], 'sheet': 'a4',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))

    def test_certificate_uses_podium_and_allows_custom_award_title(self):
        now = timezone.now()
        game = Game.objects.create(name='Export Game', team_size=1)
        winner = Team.objects.create(name='Winner', captain=self.staff, game=game, event=self.event)
        runner_up = Team.objects.create(name='Runner Up', captain=self.guest, game=game, event=self.event)
        other_team = Team.objects.create(name='Fairplay Team', captain=self.other_guest, game=game, event=self.event)
        tournament = Tournament.objects.create(
            title='Export Cup', event=self.event, game=game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            status=Tournament.Status.FINISHED, is_generated=True,
            registration_start=now - timedelta(days=2),
            registration_end=now - timedelta(days=1),
        )
        TournamentRegistration.objects.create(tournament=tournament, team=winner)
        TournamentRegistration.objects.create(tournament=tournament, team=runner_up)
        TournamentRegistration.objects.create(tournament=tournament, team=other_team)
        TournamentMatch.objects.create(
            tournament=tournament, bracket_type=TournamentMatch.BracketType.FINAL,
            status=TournamentMatch.Status.COMPLETED,
            team1=winner, team2=runner_up, winner=winner, loser=runner_up,
        )
        rows = certificate_rows([winner, runner_up, other_team], tournament, 'Fairplay')
        self.assertEqual(rows[0]['team.placement'], '1. Platz')
        self.assertEqual(rows[1]['team.placement'], '2. Platz')
        self.assertEqual(rows[0]['award.title'], 'Fairplay')
        self.assertEqual(rows[2]['team.placement'], '')
        self.assertEqual(rows[2]['award.title'], 'Fairplay')

        certificate = MediaTemplate.objects.create(
            event=self.event, name='Urkunde', kind=MediaTemplate.Kind.CERTIFICATE,
            paper_size='A4', elements=default_elements('CERTIFICATE'),
        )
        self.client.force_login(self.staff)
        response = self.client.post(reverse('media_template_export', args=[certificate.pk]), {
            'tournament': str(tournament.pk), 'recipients': [str(tournament.registrations.first().pk)],
            'award_title': 'Fairplay',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')

    def test_ffa_result_completion_makes_tournament_available_for_certificate(self):
        now = timezone.now()
        game = Game.objects.create(name='FFA Export Game', team_size=1)
        tournament = Tournament.objects.create(
            title='FFA Export Cup', event=self.event, game=game,
            mode=Tournament.Mode.FFA, status=Tournament.Status.IN_PROGRESS,
            is_generated=True, registration_start=now - timedelta(days=2),
            registration_end=now - timedelta(days=1),
        )
        match = TournamentMatch.objects.create(
            tournament=tournament, bracket_type=TournamentMatch.BracketType.FFA,
            status=TournamentMatch.Status.READY,
        )
        participants = []
        registrations = []
        for number, user in enumerate((self.staff, self.guest, self.other_guest), 1):
            team = Team.objects.create(name=f'FFA Export {number}', captain=user,
                                       game=game, event=self.event)
            participants.append(TournamentMatchParticipant.objects.create(match=match, team=team))
            registrations.append(TournamentRegistration.objects.create(tournament=tournament, team=team))
        certificate = MediaTemplate.objects.create(
            event=self.event, name='FFA Urkunde', kind=MediaTemplate.Kind.CERTIFICATE,
            paper_size='A4', elements=default_elements('CERTIFICATE'),
        )
        self.client.force_login(self.staff)
        export_url = reverse('media_template_export', args=[certificate.pk])
        self.assertNotContains(self.client.get(export_url), 'FFA Export Cup')

        score_url = reverse('match_update_ffa_score', args=[match.pk])
        scores = {f'score_{participant.pk}': 100 - number * 10
                  for number, participant in enumerate(participants)}
        self.client.post(score_url, scores)
        match.refresh_from_db()
        tournament.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.READY)
        self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)

        # Repair a match saved by the old implementation as completed without rank 1.
        match.status = TournamentMatch.Status.COMPLETED
        match.save(update_fields=['status'])
        scores.update({f'rank_{participant.pk}': number
                       for number, participant in enumerate(participants, 1)})
        self.client.post(score_url, scores)
        match.refresh_from_db()
        tournament.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertContains(self.client.get(export_url), 'FFA Export Cup')
        response = self.client.post(export_url, {
            'tournament': str(tournament.pk),
            'recipients': [str(registration.pk) for registration in registrations],
            'award_title': 'Turnierurkunde',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
