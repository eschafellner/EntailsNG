"""A complete LAN event run using guest and organizer HTTP endpoints."""

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from emails.models import GeneralEmailSettings
from events.models import Event, EventRegistration, TicketType
from seating.models import SeatingCell, SeatingPlan
from tournaments.models import Game, Team, TeamMember, Tournament, TournamentMatch, TournamentRegistration
from tournaments.services import TournamentPodiumService
from users.models import EmailVerificationCode


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_ASYNC_QUEUE=False,
)
class LanEventSimulationTests(TestCase):
    def setUp(self):
        # Rate-Limit-Zähler anderer Tests dürfen die vier Gäste dieser
        # eigenständigen Simulation nicht von der Verifizierung ausschließen.
        cache.clear()

    def test_event_from_draft_to_finished(self):
        now = timezone.now()
        event = Event.objects.create(
            title="Simulation LAN 2026",
            description="Wochenend-LAN mit Team- und Einzelturnier",
            location="Gemeindehalle",
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=3),
            max_guests=4,
        )
        self.assertEqual(event.status, Event.Status.DRAFT)
        ticket = TicketType.objects.create(event=event, name="Wochenende", price=Decimal("25.00"))
        plan = SeatingPlan.objects.create(event=event, name="Hauptsaal", columns=4, rows=1)
        for x in range(1, 5):
            SeatingCell.objects.create(
                plan=plan, x=x, y=1, cell_type=SeatingCell.CellType.SEAT,
                seat_label=f"A{x}",
            )
        event.status = Event.Status.REGISTRATION_OPEN
        event.is_active = True
        event.full_clean()
        event.save()
        self.assertEqual(Event.objects.get_active(), event)

        email_settings = GeneralEmailSettings.load()
        email_settings.transport_mode = GeneralEmailSettings.TransportMode.ENV
        email_settings.sender_email = "orga@example.test"
        email_settings.is_enabled = True
        email_settings.save()

        organizer = get_user_model().objects.create_superuser(
            username="lan_orga", email="orga@example.test", password="TestPass123!",
        )
        staff = Client()
        staff.force_login(organizer)

        guests = []
        for index in range(1, 5):
            browser = Client()
            username = f"lan_gast_{index}"
            with self.captureOnCommitCallbacks(execute=True):
                response = browser.post(reverse("register"), {
                    "username": username,
                    "email": f"{username}@example.test",
                    "birthday": "2000-05-15",
                    "password1": "TestPass123!",
                    "password2": "TestPass123!",
                })
            self.assertRedirects(response, reverse("verify_email"))
            user = get_user_model().objects.get(username=username)
            self.assertFalse(user.is_active)
            self.assertTrue(any(user.email in message.to for message in mail.outbox))
            code = EmailVerificationCode.objects.filter(user=user, is_used=False).first()
            self.assertIsNotNone(code)
            response = browser.post(reverse("verify_email"), {"code": code.code})
            self.assertRedirects(response, reverse("dashboard"))
            user.refresh_from_db()
            self.assertTrue(user.is_active)
            code.refresh_from_db()
            self.assertTrue(code.is_used)

            response = browser.post(
                reverse("register_for_event", args=[event.pk]),
                {"ticket_type_id": ticket.pk},
            )
            self.assertRedirects(response, reverse("dashboard"))
            registration = EventRegistration.objects.get(user=user, event=event)
            self.assertEqual(registration.booking_price, Decimal("25.00"))
            self.assertEqual(registration.payment_status, EventRegistration.PaymentStatus.UNPAID)

            response = browser.post(
                reverse("api_reserve_seat", args=[event.pk]),
                json.dumps({"x": index, "y": 1}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            seat = SeatingCell.objects.get(plan=plan, x=index, y=1)
            self.assertEqual(seat.reservation_status, SeatingCell.ReservationStatus.PRE_RESERVED)

            # An unpaid ticket must be rejected by the actual scanner endpoint.
            response = staff.post(
                reverse("api_scan_qr"),
                json.dumps({"code": registration.short_code}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()["status"], "unpaid")

            registration.mark_as_paid(send_email=False)
            registration.refresh_from_db()
            self.assertEqual(registration.paid_amount, Decimal("25.00"))
            seat.refresh_from_db()
            self.assertEqual(seat.reservation_status, SeatingCell.ReservationStatus.RESERVED)
            response = browser.get(reverse("registration_checkin_qr", args=[registration.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/png")

            guests.append((user, browser, registration))

        self.assertEqual(event.active_registrations_count, 4)
        self.assertTrue(event.is_full)
        event.start_date = now - timedelta(hours=1)
        event.status = Event.Status.RUNNING
        event.save()
        self.assertEqual(event.effective_status, Event.Status.RUNNING)

        for user, _, registration in guests:
            response = staff.post(
                reverse("api_scan_qr"),
                json.dumps({"code": str(registration.checkin_token)}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["status"], "success")
            self.assertEqual(response.json()["seat"], registration.seat_label)
            registration.refresh_from_db()
            self.assertTrue(registration.is_checked_in)
            self.assertIsNotNone(registration.checked_in_at)
        response = staff.get(reverse("checkin_scanner"))
        self.assertEqual(response.context["checked_in_count"], 4)

        team_game = Game.objects.create(name="Simulation Arena", team_size=2)
        solo_game = Game.objects.create(name="Simulation Duel", team_size=1)
        team_tournament = self.make_tournament(event, team_game, "Team-Cup", now)
        solo_tournament = self.make_tournament(event, solo_game, "Solo-Cup", now)

        teams = []
        for team_number, member_indexes in enumerate(((0, 1), (2, 3)), start=1):
            captain, captain_browser, _ = guests[member_indexes[0]]
            name = f"Squad {team_number}"
            response = captain_browser.post(reverse("team_create"), {
                "name": name, "tag": f"S{team_number}", "game_id": team_game.pk,
            })
            team = Team.objects.get(name=name)
            self.assertRedirects(response, reverse("team_detail", kwargs={"slug": team.slug}))
            member, member_browser, _ = guests[member_indexes[1]]
            response = member_browser.post(reverse("team_apply", kwargs={"slug": team.slug}))
            self.assertEqual(response.status_code, 302)
            membership = TeamMember.objects.get(team=team, user=member)
            self.assertEqual(membership.status, TeamMember.Status.PENDING)
            response = captain_browser.post(reverse("team_accept_membership", kwargs={
                "slug": team.slug, "membership_id": membership.pk,
            }))
            self.assertEqual(response.status_code, 302)
            membership.refresh_from_db()
            self.assertEqual(membership.status, TeamMember.Status.ACCEPTED)
            response = captain_browser.post(
                reverse("tournament_register", kwargs={"slug": team_tournament.slug}),
                {"team_id": team.pk},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(TournamentRegistration.objects.filter(tournament=team_tournament, team=team).exists())
            teams.append(team)

        for user, browser, _ in guests:
            response = browser.post(reverse("tournament_register", kwargs={"slug": solo_tournament.slug}))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(TournamentRegistration.objects.filter(
                tournament=solo_tournament, team__captain=user,
            ).exists())

        self.assertEqual(team_tournament.registrations.count(), 2)
        self.assertEqual(solo_tournament.registrations.count(), 4)
        for tournament, expected_matches in ((team_tournament, 1), (solo_tournament, 3)):
            response = staff.post(reverse("tournament_generate_bracket", kwargs={"slug": tournament.slug}))
            self.assertEqual(response.status_code, 302)
            tournament.refresh_from_db()
            self.assertTrue(tournament.is_generated)
            self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)
            self.assertEqual(tournament.matches.count(), expected_matches)

            while tournament.status != Tournament.Status.FINISHED:
                if tournament.status == Tournament.Status.RESULTS_REVIEW:
                    from tournaments.services import TournamentLifecycleService
                    TournamentLifecycleService.confirm_results(tournament.pk, actor=organizer)
                    tournament.refresh_from_db()
                    break
                ready = tournament.matches.filter(status=TournamentMatch.Status.READY).order_by(
                    "round_number", "match_number",
                ).first()
                self.assertIsNotNone(ready, f"No playable match in {tournament.title}")
                self.assertIsNotNone(ready.team1_id)
                self.assertIsNotNone(ready.team2_id)
                response = staff.post(reverse("match_update_score", args=[ready.pk]), {
                    "score_team1": 2, "score_team2": 1, "winner_id": ready.team1_id,
                })
                self.assertEqual(response.status_code, 200, response.content)
                self.assertTrue(response.json()["success"])
                tournament.refresh_from_db()

            self.assertFalse(tournament.matches.exclude(status=TournamentMatch.Status.COMPLETED).exists())
            podium = TournamentPodiumService.calculate(tournament)
            self.assertIsNotNone(podium["first"])
            self.assertIsNotNone(podium["second"])

        self.assertIn(TournamentPodiumService.calculate(team_tournament)["first"], teams)
        event.end_date = now
        event.save(update_fields=["end_date"])
        finish_url = reverse("admin:events_event_changelist")
        action_data = {"action": "action_finish_event", "_selected_action": [event.pk]}
        response = staff.post(finish_url, action_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Veranstaltung jetzt abschließen")
        response = staff.post(finish_url, {**action_data, "confirm_finish": "1"})
        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.effective_status, Event.Status.FINISHED)
        self.assertIsNone(Event.objects.get_active())
        self.assertFalse(event.can_register()[0])
        self.assertEqual(Team.objects.filter(event=event, is_archived=True).count(), 6)
        self.assertEqual(EventRegistration.objects.filter(event=event, is_checked_in=True).count(), 4)
        response = guests[0][1].get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(guests[0][2], response.context["past_registrations"])

    def make_tournament(self, event, game, title, now):
        return Tournament.objects.create(
            event=event, game=game, title=title,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            max_teams=4,
            registration_start=now - timedelta(hours=1),
            registration_end=now + timedelta(hours=2),
            tournament_start=now + timedelta(hours=3),
            status=Tournament.Status.REGISTRATION_OPEN,
        )
