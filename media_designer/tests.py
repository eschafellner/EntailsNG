from datetime import datetime, timedelta, timezone as datetime_timezone
from io import BytesIO
from io import StringIO
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageChops

from events.models import Event, EventRegistration
from configuration.models import SystemTranslation
from media_designer.data import badge_rows, certificate_rows
from media_designer.models import MediaFont, MediaTemplate
from media_designer.rendering import render_card, render_pdf, sheet_layout
from media_designer.schema import default_elements, translated_field_labels
from seating.models import SeatingCell, SeatingPlan
from tournaments.exceptions import TournamentMatchError
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentMatchParticipant,
    TournamentRegistration,
)
from tournaments.services import FFAMatchService
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

    def test_seeded_media_texts_are_editable_and_seed_preserves_changes(self):
        call_command('seed_translations', stdout=StringIO())
        for key in (
            'media_form_name', 'media_kind_badge', 'media_field_event_start',
            'media_field_team_members', 'media_award_default',
            'media_filter_paid', 'media_filter_seat', 'media_font_family',
            'media_font_default', 'media_error_font_missing',
            'tournament_ffa_rank_required', 'tournament_ffa_error_duplicate_winner',
        ):
            self.assertTrue(SystemTranslation.objects.filter(key=key).exists(), key)

        name_translation = SystemTranslation.objects.get(key='media_form_name')
        name_translation.text = 'Vorlagenname für die Orga'
        name_translation.save()
        kind_translation = SystemTranslation.objects.get(key='media_kind_badge')
        kind_translation.text = 'LAN Yard Badge'
        kind_translation.save()
        field_translation = SystemTranslation.objects.get(key='media_field_event_start')
        field_translation.text = 'Start der LAN'
        field_translation.save()
        award_translation = SystemTranslation.objects.get(key='media_award_default')
        award_translation.text = 'Sonderurkunde'
        award_translation.save()
        ffa_translation = SystemTranslation.objects.get(key='tournament_ffa_error_no_scores')
        ffa_translation.text = 'Bitte FFA-Wertung eingeben.'
        ffa_translation.save()
        call_command('seed_translations', stdout=StringIO())
        name_translation.refresh_from_db()
        self.assertEqual(name_translation.text, 'Vorlagenname für die Orga')

        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse('media_template_list')), 'Vorlagenname für die Orga')
        self.assertContains(self.client.get(reverse('media_template_list')), 'LAN Yard Badge')
        self.assertEqual(translated_field_labels()['BADGE']['event.start_date'], 'Start der LAN')
        certificate = MediaTemplate.objects.create(
            event=self.event, name='Sonderpreis', kind=MediaTemplate.Kind.CERTIFICATE,
            paper_size='A4', created_by=self.staff,
        )
        self.assertContains(
            self.client.get(reverse('media_template_export', args=[certificate.pk])),
            'value="Sonderurkunde"',
        )
        with self.assertRaisesMessage(TournamentMatchError, 'Bitte FFA-Wertung eingeben.'):
            FFAMatchService.update_ffa_scores(0, [])

    def test_badge_fields_include_event_start_and_end_in_local_time(self):
        self.event.start_date = datetime(2026, 9, 25, 16, 0, tzinfo=datetime_timezone.utc)
        self.event.end_date = datetime(2026, 9, 27, 9, 30, tzinfo=datetime_timezone.utc)
        self.event.save(update_fields=['start_date', 'end_date'])

        rows = badge_rows([self.registration], self.event)
        self.assertEqual(rows[0]['event.start_date'], '25.09.2026 18:00')
        self.assertEqual(rows[0]['event.end_date'], '27.09.2026 11:30')
        self.assertIn('event.start_date', translated_field_labels()['BADGE'])
        self.assertIn('event.end_date', translated_field_labels()['BADGE'])

        self.badge.elements = [
            {**default_elements('BADGE')[0], 'source': 'event.start_date'},
            {**default_elements('BADGE')[1], 'source': 'event.end_date'},
        ]
        self.badge.full_clean()
        self.client.force_login(self.staff)
        editor = self.client.get(reverse('media_template_edit', args=[self.badge.pk]))
        self.assertContains(editor, 'data-sample-start="25.09.2026 18:00"')
        self.assertContains(editor, 'event.start_date')
        pdf = render_pdf(self.badge, rows)
        try:
            self.assertTrue(pdf.read().startswith(b'%PDF-'))
        finally:
            pdf.close()

    def test_certificate_team_members_include_only_accepted_members_on_separate_lines(self):
        game = Game.objects.create(name='Team Export Game', team_size=2)
        team = Team.objects.create(name='Team Export', captain=self.staff,
                                   game=game, event=self.event)
        TeamMember.objects.create(team=team, user=self.staff, status=TeamMember.Status.ACCEPTED)
        TeamMember.objects.create(team=team, user=self.guest, status=TeamMember.Status.ACCEPTED)
        TeamMember.objects.create(team=team, user=self.other_guest, status=TeamMember.Status.PENDING)
        now = timezone.now()
        tournament = Tournament.objects.create(
            title='Team Export Cup', event=self.event, game=game,
            status=Tournament.Status.FINISHED, registration_start=now - timedelta(days=2),
            registration_end=now - timedelta(days=1),
        )
        rows = certificate_rows([team], tournament, 'Teamurkunde')
        self.assertEqual(rows[0]['team.members'], 'export-staff\nexport-guest')
        self.assertEqual(rows[0]['event.title'], self.event.title)
        self.assertIn('team.members', translated_field_labels()['CERTIFICATE'])
        self.assertIn('event.start_date', translated_field_labels()['CERTIFICATE'])
        self.assertIn('event.end_date', translated_field_labels()['CERTIFICATE'])

        certificate = MediaTemplate.objects.create(
            event=self.event, name='Mitgliederurkunde', kind=MediaTemplate.Kind.CERTIFICATE,
            created_by=self.staff,
            paper_size='A4', elements=[
                {**default_elements('CERTIFICATE')[1], 'source': 'team.members',
                 'y': 0.55, 'font_size_mm': 5},
            ],
        )
        certificate.full_clean()
        self.client.force_login(self.staff)
        self.assertContains(
            self.client.get(reverse('media_template_edit', args=[certificate.pk])),
            'team.members',
        )
        card = render_card(certificate, rows[0])
        try:
            top = round(0.55 * card.height)
            text_area = card.crop((0, top, card.width, top + 200)).convert('L')
            ink_rows = [text_area.crop((0, y, text_area.width, y + 1)).getextrema()[0] < 200
                        for y in range(text_area.height)]
            self.assertEqual(sum(ink and (y == 0 or not ink_rows[y - 1])
                                 for y, ink in enumerate(ink_rows)), 2)
        finally:
            card.close()
        pdf = render_pdf(certificate, rows)
        try:
            self.assertTrue(pdf.read().startswith(b'%PDF-'))
        finally:
            pdf.close()

    def test_invalid_fields_are_rejected_before_rendering(self):
        self.badge.elements = [{**default_elements('BADGE')[0], 'source': 'guest.email'}]
        with self.assertRaises(ValidationError):
            self.badge.full_clean()
        with self.assertRaises(ValidationError):
            render_pdf(self.badge, [{'guest.email': 'private@example.test'}])

    def test_managed_font_is_selectable_and_used_in_pdf_rendering(self):
        font_bytes = (Path(settings.BASE_DIR) / 'static/fonts/dm-sans-normal-400-latin.woff2').read_bytes()
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            font = MediaFont(
                name='DM Sans Test',
                file=SimpleUploadedFile('dm-sans.woff2', font_bytes, content_type='font/woff2'),
            )
            font.full_clean()
            font.save()
            self.client.force_login(self.staff)
            editor = self.client.get(reverse('media_template_edit', args=[self.badge.pk]))
            self.assertContains(editor, 'DM Sans Test')
            self.assertContains(editor, 'media-fonts')
            self.assertContains(editor, 'Schriftart')

            values = {'guest.username': 'Gamer-Test', 'guest.seat': 'A-12'}
            default_card = render_card(self.badge, values)
            self.badge.elements[0]['font_id'] = font.pk
            self.badge.full_clean()
            selected_card = render_card(self.badge, values)
            try:
                self.assertIsNotNone(ImageChops.difference(default_card, selected_card).getbbox())
            finally:
                default_card.close()
                selected_card.close()
            pdf = render_pdf(self.badge, [values])
            try:
                self.assertTrue(pdf.read().startswith(b'%PDF-'))
            finally:
                pdf.close()

            response = self.client.post(reverse('media_template_edit', args=[self.badge.pk]), {
                'event': self.event.pk, 'name': self.badge.name,
                'paper_size': self.badge.paper_size, 'elements': json.dumps(self.badge.elements),
            })
            self.assertEqual(response.status_code, 302)
            self.badge.refresh_from_db()
            self.assertEqual(self.badge.elements[0]['font_id'], font.pk)
            font_name = font.file.name
            with self.captureOnCommitCallbacks(execute=True):
                font.delete()
            self.badge.refresh_from_db()
            self.assertNotIn('font_id', self.badge.elements[0])
            self.assertFalse(font.file.storage.exists(font_name))
            self.badge.full_clean()

    def test_unknown_font_and_invalid_upload_are_rejected(self):
        self.badge.elements[0]['font_id'] = 999999
        with self.assertRaises(ValidationError):
            self.badge.full_clean()
        self.badge.elements[0]['font_id'] = True
        with self.assertRaises(ValidationError):
            self.badge.full_clean()

        font = MediaFont(name='Broken', file=SimpleUploadedFile(
            'broken.ttf', b'not a font', content_type='font/ttf'
        ))
        with self.assertRaises(ValidationError):
            font.full_clean()

    def test_admin_can_add_and_delete_font(self):
        font_bytes = (Path(settings.BASE_DIR) / 'static/fonts/dm-sans-normal-400-latin.woff2').read_bytes()
        admin_user = User.objects.create_superuser(username='font-admin', password='test-password')
        self.client.force_login(admin_user)
        add_url = reverse('admin:media_designer_mediafont_add')
        self.assertContains(self.client.get(add_url), 'Schriftdatei')
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(add_url, {
                'name': 'Neue Urkundenschrift',
                'file': SimpleUploadedFile('custom.woff2', font_bytes, content_type='font/woff2'),
            })
            self.assertEqual(response.status_code, 302)
            font = MediaFont.objects.get(name='Neue Urkundenschrift')
            self.assertTrue(font.file.storage.exists(font.file.name))
            delete_url = reverse('admin:media_designer_mediafont_delete', args=[font.pk])
            self.assertEqual(self.client.get(delete_url).status_code, 200)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(delete_url, {'post': 'yes'})
            self.assertEqual(response.status_code, 302)
            self.assertFalse(MediaFont.objects.filter(pk=font.pk).exists())

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

    def test_badge_filters_combine_payment_and_seat_and_limit_export(self):
        plan = SeatingPlan.objects.create(event=self.event, name='Badge Filter Hall')
        registrations = {'unpaid_no_seat': self.registration}
        for name, status in (
            ('paid_with_seat', EventRegistration.PaymentStatus.PAID),
            ('paid_no_seat', EventRegistration.PaymentStatus.PAID),
            ('unpaid_with_seat', EventRegistration.PaymentStatus.UNPAID),
            ('cancelled_with_seat', EventRegistration.PaymentStatus.CANCELLED),
        ):
            user = User.objects.create_user(username=name)
            registrations[name] = EventRegistration.objects.create(
                user=user, event=self.event, payment_status=status,
            )
        for x, name in enumerate(('paid_with_seat', 'unpaid_with_seat', 'cancelled_with_seat'), 1):
            SeatingCell.objects.create(
                plan=plan, x=x, y=1, cell_type=SeatingCell.CellType.SEAT,
                registration=registrations[name], seat_label=f'A-{x}',
            )

        self.client.force_login(self.staff)
        url = reverse('media_template_export', args=[self.badge.pk])
        cases = {
            ('all', 'all'): {'unpaid_no_seat', 'paid_with_seat', 'paid_no_seat', 'unpaid_with_seat'},
            ('yes', 'all'): {'paid_with_seat', 'paid_no_seat'},
            ('no', 'all'): {'unpaid_no_seat', 'unpaid_with_seat'},
            ('all', 'yes'): {'paid_with_seat', 'unpaid_with_seat'},
            ('all', 'no'): {'unpaid_no_seat', 'paid_no_seat'},
            ('yes', 'yes'): {'paid_with_seat'},
            ('yes', 'no'): {'paid_no_seat'},
            ('no', 'yes'): {'unpaid_with_seat'},
            ('no', 'no'): {'unpaid_no_seat'},
        }
        for (paid, seat), expected in cases.items():
            with self.subTest(paid=paid, seat=seat):
                response = self.client.get(url, {'paid': paid, 'seat': seat})
                self.assertEqual(
                    {registration.pk for registration in response.context['recipients']},
                    {registrations[name].pk for name in expected},
                )
                self.assertContains(response, f'name="paid" value="{paid}"')
                self.assertContains(response, f'name="seat" value="{seat}"')

        filtered = {'paid': 'yes', 'seat': 'yes', 'sheet': 'single'}
        response = self.client.post(url, {
            **filtered, 'recipients': [str(registrations['unpaid_with_seat'].pk)],
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context['payment_filter'], 'yes')
        self.assertEqual(response.context['seat_filter'], 'yes')
        response = self.client.post(url, {
            **filtered, 'recipients': [str(registrations['paid_with_seat'].pk)],
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
