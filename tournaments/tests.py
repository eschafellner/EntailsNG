from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from users.models import User
from events.models import Event, EventRegistration
from tournaments.exceptions import (
    InvalidWinnerError, MatchAlreadyCompletedError, TournamentError, TournamentRegistrationError, TournamentNotCheckedInError
)
from tournaments.models import (
    Game, Team, TeamMember, Tournament, TournamentMatch, TournamentMatchParticipant, TournamentRegistration
)
from tournaments.services import (
    FFAMatchService,
    GroupStageStandingService,
    LeagueStandingService,
    TournamentMatchService,
    TournamentRegistrationService,
    advance_match_winner,
    check_user_event_checkin,
    generate_bracket,
    get_or_create_solo_team,
)


class TournamentModelTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Test LAN 2026",
            slug="test-lan-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(
            name="CS2",
            mode="5v5 Bomb",
            team_size=5
        )
        self.user1 = User.objects.create_user(username="player1", email="p1@example.com", password="pass")
        self.user2 = User.objects.create_user(username="player2", email="p2@example.com", password="pass")
        self.user3 = User.objects.create_user(username="player3", email="p3@example.com", password="pass")

    def test_game_slug_generation(self):
        self.assertEqual(self.game.slug, "cs2")

    def test_team_creation_and_invite_code(self):
        team = Team.objects.create(name="Team Rocket", captain=self.user1, game=self.game)
        self.assertIsNotNone(team.invite_code)
        self.assertEqual(len(team.invite_code), 8)

    def test_team_leave_logic(self):
        team = Team.objects.create(name="Alpha Team", captain=self.user1, game=self.game)
        m1 = TeamMember.objects.create(team=team, user=self.user1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        m2 = TeamMember.objects.create(team=team, user=self.user2, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)

        # 1. Non-captain leaves
        res = team.leave_team(self.user2)
        self.assertEqual(res, 'left')
        self.assertFalse(TeamMember.objects.filter(team=team, user=self.user2).exists())

        # 2. Add user3, then captain user1 leaves -> captain rank transferred to user3
        TeamMember.objects.create(team=team, user=self.user3, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)
        res2 = team.leave_team(self.user1)
        self.assertEqual(res2, 'captain_transferred')
        team.refresh_from_db()
        self.assertEqual(team.captain, self.user3)

        # 3. Last member leaves -> team deleted
        res3 = team.leave_team(self.user3)
        self.assertEqual(res3, 'deleted')
        self.assertFalse(Team.objects.filter(id=team.id).exists())

    def test_solo_team_auto_creation(self):
        solo_team = get_or_create_solo_team(self.user1, self.game)
        self.assertTrue(solo_team.is_solo)
        self.assertEqual(solo_team.captain, self.user1)
        self.assertTrue(solo_team.is_member(self.user1))

    def test_user_event_checkin_validation(self):
        self.assertFalse(check_user_event_checkin(self.user1, self.event))
        reg = EventRegistration.objects.create(
            user=self.user1,
            event=self.event,
            payment_status=EventRegistration.PaymentStatus.PAID,
            is_checked_in=True
        )
        self.assertTrue(check_user_event_checkin(self.user1, self.event))


    def test_single_elimination_bracket_generation_with_byes(self):
        tournament = Tournament.objects.create(
            title="CS2 Cup",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
        )

        # Create 3 teams (next power of 2 is 4, 1 BYE)
        t1 = Team.objects.create(name="Team 1", captain=self.user1)
        t2 = Team.objects.create(name="Team 2", captain=self.user2)
        t3 = Team.objects.create(name="Team 3", captain=self.user3)

        TournamentRegistration.objects.create(tournament=tournament, team=t1)
        TournamentRegistration.objects.create(tournament=tournament, team=t2)
        TournamentRegistration.objects.create(tournament=tournament, team=t3)

        # Preview Test
        preview = generate_bracket(tournament, preview=True)
        self.assertEqual(preview['mode'], 'SINGLE_ELIMINATION')
        self.assertEqual(preview['total_teams'], 3)
        self.assertEqual(preview['byes'], 1)

        # Real Generation Test
        res = generate_bracket(tournament, preview=False)
        self.assertTrue(res)
        tournament.refresh_from_db()
        self.assertTrue(tournament.is_generated)
        self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)

        # Check matches in DB
        matches = TournamentMatch.objects.filter(tournament=tournament)
        self.assertEqual(matches.count(), 3)  # 2 in R1, 1 in R2 (Final)
        bye_match = matches.filter(is_bye=True).first()
        self.assertIsNotNone(bye_match)
        self.assertEqual(bye_match.status, TournamentMatch.Status.COMPLETED)

    def test_advance_match_winner(self):
        tournament = Tournament.objects.create(
            title="CS2 1v1",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
        )

        t1 = Team.objects.create(name="Team A", captain=self.user1)
        t2 = Team.objects.create(name="Team B", captain=self.user2)

        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            team1=t1,
            team2=t2,
            status=TournamentMatch.Status.READY
        )

        advance_match_winner(match, t1, score1=16, score2=14)
        match.refresh_from_db()

        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(match.winner, t1)
        self.assertEqual(match.loser, t2)
        self.assertEqual(match.score_team1, 16)
        self.assertEqual(match.score_team2, 14)

    def test_match_update_score_view_rejects_unrelated_team(self):
        self.user1.is_staff = True
        self.user1.save()
        self.client.login(username="player1", password="pass")

        tournament = Tournament.objects.create(
            title="CS2 1v1",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
        )
        t1 = Team.objects.create(name="Team A", captain=self.user1)
        t2 = Team.objects.create(name="Team B", captain=self.user2)
        unrelated_team = Team.objects.create(name="Team Unrelated", captain=self.user3)

        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            team1=t1,
            team2=t2,
            status=TournamentMatch.Status.READY
        )

        from django.urls import reverse
        # Versuch ein unbeteiligtes Team als Sieger zu übergeben
        response = self.client.post(
            reverse('match_update_score', kwargs={'match_id': match.id}),
            {'score_team1': 16, 'score_team2': 14, 'winner_id': unrelated_team.id}
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

        # Mit korrektem Teilnehmer
        good_response = self.client.post(
            reverse('match_update_score', kwargs={'match_id': match.id}),
            {'score_team1': 16, 'score_team2': 14, 'winner_id': t1.id}
        )
        self.assertEqual(good_response.status_code, 200)
        self.assertTrue(good_response.json()['success'])

    def test_team_kick_member_prevents_captain_self_kick(self):
        team = Team.objects.create(name="Captain Test", captain=self.user1, game=self.game)
        TeamMember.objects.create(team=team, user=self.user1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        TeamMember.objects.create(team=team, user=self.user2, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)

        self.client.login(username="player1", password="pass")
        from django.urls import reverse
        # Kapitän versucht sich selbst zu kicken
        response = self.client.post(
            reverse('team_kick_member', kwargs={'slug': team.slug, 'user_id': self.user1.id})
        )
        self.assertRedirects(response, reverse('team_detail', kwargs={'slug': team.slug}))
        self.assertTrue(TeamMember.objects.filter(team=team, user=self.user1).exists())

        # Kapitän kickt reguläres Mitglied
        response_kick = self.client.post(
            reverse('team_kick_member', kwargs={'slug': team.slug, 'user_id': self.user2.id})
        )
        self.assertRedirects(response_kick, reverse('team_detail', kwargs={'slug': team.slug}))
        self.assertFalse(TeamMember.objects.filter(team=team, user=self.user2).exists())

    def test_team_created_with_active_event(self):
        """Positiver Test: Neu gegründetes Team wird automatisch dem aktiven Event zugeordnet."""
        from django.urls import reverse
        self.client.login(username="player1", password="pass")
        response = self.client.post(
            reverse('team_create'),
            {'name': 'Active Event Team', 'tag': 'AET', 'game_id': self.game.id}
        )
        team = Team.objects.get(name='Active Event Team')
        self.assertEqual(team.event, self.event)
        self.assertFalse(team.is_archived)

    def test_archive_teams_for_event_service(self):
        """Positiver Test: Service archive_teams_for_event archiviert alle Teams des Events."""
        from tournaments.services import archive_teams_for_event
        t1 = Team.objects.create(name="Team LAN 1", captain=self.user1, event=self.event)
        t2 = Team.objects.create(name="Team LAN 2", captain=self.user2, event=self.event)

        count = archive_teams_for_event(self.event)
        self.assertEqual(count, 2)
        t1.refresh_from_db()
        t2.refresh_from_db()
        self.assertTrue(t1.is_archived)
        self.assertTrue(t2.is_archived)

    def test_team_reactivation_positive(self):
        """Positiver Test: Kapitän reaktiviert archiviertes Team für neues Event mit Roster-Auswahl."""
        from django.urls import reverse
        # Neues Event anlegen und aktivieren
        self.event.is_active = False
        self.event.save()

        event_2027 = Event.objects.create(
            title="Haag-networX 2027",
            slug="haag-2027",
            is_active=True,
            start_date=timezone.now() + timedelta(days=365),
            end_date=timezone.now() + timedelta(days=367),
        )

        # User1 hat Ticket für 2027, User2 hat keines
        EventRegistration.objects.create(user=self.user1, event=event_2027)

        # Altes archiviertes Team
        old_team = Team.objects.create(
            name="Veterans",
            captain=self.user1,
            game=self.game,
            event=self.event,
            is_archived=True,
        )
        TeamMember.objects.create(team=old_team, user=self.user1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        TeamMember.objects.create(team=old_team, user=self.user2, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)

        self.client.login(username="player1", password="pass")

        # GET Reaktivierungs-Assistent
        get_res = self.client.get(reverse('team_reactivate', kwargs={'slug': old_team.slug}))
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, "Smart Roster Check")
        self.assertContains(get_res, "player1")
        self.assertContains(get_res, "player2")

        # POST Reaktivierung: Nur player1 behalten, player2 wird abgewählt
        post_res = self.client.post(
            reverse('team_reactivate', kwargs={'slug': old_team.slug}),
            {
                'game_id': self.game.id,
                'keep_members': [self.user1.id],
                'reset_invite_code': '1',
            }
        )
        self.assertRedirects(post_res, reverse('team_detail', kwargs={'slug': old_team.slug}))

        old_team.refresh_from_db()
        self.assertEqual(old_team.event, event_2027)
        self.assertFalse(old_team.is_archived)
        self.assertEqual(old_team.memberships.count(), 1)
        self.assertTrue(old_team.memberships.filter(user=self.user1).exists())
        self.assertFalse(old_team.memberships.filter(user=self.user2).exists())

    def test_negative_non_captain_cannot_reactivate_team(self):
        """Negativer Test: Normales Teammitglied kann ein Team nicht reaktivieren."""
        from django.urls import reverse
        old_team = Team.objects.create(
            name="Alpha Squad",
            captain=self.user1,
            event=self.event,
            is_archived=True,
        )
        TeamMember.objects.create(team=old_team, user=self.user1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        TeamMember.objects.create(team=old_team, user=self.user2, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)

        # Login als User2 (nicht Kapitän)
        self.client.login(username="player2", password="pass")
        response = self.client.post(
            reverse('team_reactivate', kwargs={'slug': old_team.slug}),
            {'keep_members': [self.user2.id]}
        )
        self.assertRedirects(response, reverse('team_detail', kwargs={'slug': old_team.slug}))
        old_team.refresh_from_db()
        self.assertTrue(old_team.is_archived)
        self.assertEqual(old_team.event, self.event)

    def test_negative_cannot_reactivate_without_active_event(self):
        """Negativer Test: Reaktivierung scheitert, wenn keine aktive Veranstaltung existiert."""
        from django.urls import reverse
        self.event.is_active = False
        self.event.save()

        old_team = Team.objects.create(
            name="No Event Team",
            captain=self.user1,
            event=self.event,
            is_archived=True,
        )
        TeamMember.objects.create(team=old_team, user=self.user1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.client.login(username="player1", password="pass")
        response = self.client.get(reverse('team_reactivate', kwargs={'slug': old_team.slug}))
        self.assertRedirects(response, reverse('team_detail', kwargs={'slug': old_team.slug}))


class TournamentHardeningServiceTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Winter LAN 2026",
            slug="winter-lan-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=3),
        )
        self.game = Game.objects.create(
            name="Rocket League",
            mode="3v3",
            team_size=3
        )
        self.admin_user = User.objects.create_superuser(username="admin_user", email="admin@example.com", password="password")
        self.u1 = User.objects.create_user(username="u1", email="u1@example.com", password="password")
        self.u2 = User.objects.create_user(username="u2", email="u2@example.com", password="password")
        self.u3 = User.objects.create_user(username="u3", email="u3@example.com", password="password")
        self.u4 = User.objects.create_user(username="u4", email="u4@example.com", password="password")

        # Check-in für alle Test-User auf dem Event anlegen
        for u in [self.u1, self.u2, self.u3, self.u4]:
            EventRegistration.objects.create(
                user=u,
                event=self.event,
                payment_status=EventRegistration.PaymentStatus.PAID,
                is_checked_in=True,
            )

        # Teams anlegen mit je 3 eingecheckten Mitgliedern
        for idx, (cap, t_name) in enumerate([(self.u1, "Team Alpha"), (self.u2, "Team Beta"), (self.u3, "Team Gamma"), (self.u4, "Team Delta")], 1):
            team = Team.objects.create(name=t_name, captain=cap, game=self.game, event=self.event)
            TeamMember.objects.create(team=team, user=cap, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
            for m_idx in [1, 2]:
                extra_u = User.objects.create_user(username=f"t{idx}_m{m_idx}", password="password")
                EventRegistration.objects.create(user=extra_u, event=self.event, is_checked_in=True)
                TeamMember.objects.create(team=team, user=extra_u, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)
            setattr(self, f"team{idx}", team)

    def test_registration_window_and_status_enforcement(self):
        """Punkt 1: Anmeldung prüft exakt das Zeitfenster (Start, Ende) und den Status."""
        from tournaments.exceptions import TournamentNotOpenError
        from tournaments.services import TournamentRegistrationService

        # 1. Zu früh (Anmeldung in Zukunft)
        t_future = Tournament.objects.create(
            title="Future Tournament",
            event=self.event,
            game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() + timedelta(hours=2),
            registration_end=timezone.now() + timedelta(days=1),
        )
        self.assertFalse(t_future.is_registration_open)
        with self.assertRaises(TournamentNotOpenError):
            TournamentRegistrationService.register_team(t_future.id, self.u1, self.team1.id)

        # 2. Zu spät (Anmeldeschluss vorbei)
        t_past = Tournament.objects.create(
            title="Past Tournament",
            event=self.event,
            game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(days=2),
            registration_end=timezone.now() - timedelta(hours=1),
        )
        self.assertFalse(t_past.is_registration_open)
        with self.assertRaises(TournamentNotOpenError):
            TournamentRegistrationService.register_team(t_past.id, self.u1, self.team1.id)

        # 3. Status nicht OPEN (z. B. DRAFT) obwohl Zeitfenster passt
        t_draft = Tournament.objects.create(
            title="Draft Tournament",
            event=self.event,
            game=self.game,
            status=Tournament.Status.DRAFT,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        self.assertFalse(t_draft.is_registration_open)
        with self.assertRaises(TournamentNotOpenError):
            TournamentRegistrationService.register_team(t_draft.id, self.u1, self.team1.id)

        # 4. Offenes Zeitfenster -> Erfolgreich
        t_open = Tournament.objects.create(
            title="Open Tournament",
            event=self.event,
            game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        self.assertTrue(t_open.is_registration_open)
        reg, created = TournamentRegistrationService.register_team(t_open.id, self.u1, self.team1.id)
        self.assertTrue(created)
        self.assertEqual(reg.team, self.team1)

    def test_team_limit_and_concurrency_protection(self):
        """Punkt 2: Teamlimit wird strikt durchgesetzt."""
        from tournaments.exceptions import TournamentFullError, TournamentAlreadyRegisteredError
        from tournaments.services import TournamentRegistrationService

        tournament = Tournament.objects.create(
            title="Cap 2 Tournament",
            event=self.event,
            game=self.game,
            max_teams=2,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )

        # Team 1 & Team 2 registrieren
        TournamentRegistrationService.register_team(tournament.id, self.u1, self.team1.id)
        TournamentRegistrationService.register_team(tournament.id, self.u2, self.team2.id)

        # Team 3 versucht beizutreten -> TournamentFullError
        with self.assertRaises(TournamentFullError):
            TournamentRegistrationService.register_team(tournament.id, self.u3, self.team3.id)

        # Team 1 versucht sich erneut anzumelden -> TournamentAlreadyRegisteredError
        with self.assertRaises(TournamentAlreadyRegisteredError):
            TournamentRegistrationService.register_team(tournament.id, self.u1, self.team1.id)

    def test_failed_bracket_generation_does_not_close_tournament(self):
        """Punkt 3: Fehlgeschlagene Bracket-Generierung (< 2 Teams) ändert den Status nicht."""
        from tournaments.exceptions import InsufficientTeamsError
        from tournaments.services import TournamentBracketService

        tournament = Tournament.objects.create(
            title="Solo Registered Tournament",
            event=self.event,
            game=self.game,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        # Nur 1 Team
        TournamentRegistration.objects.create(tournament=tournament, team=self.team1)

        with self.assertRaises(InsufficientTeamsError):
            TournamentBracketService.generate_bracket(tournament.id)

        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.REGISTRATION_OPEN)
        self.assertFalse(tournament.is_generated)

    def test_bracket_regeneration_protection_and_reset(self):
        """Punkt 4: Turnierbaum kann nicht versehentlich neu generiert werden; Reset ist abgesichert."""
        from tournaments.exceptions import BracketAlreadyGeneratedError, TournamentBracketError
        from tournaments.services import TournamentBracketService

        tournament = Tournament.objects.create(
            title="KO Cup",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        TournamentRegistration.objects.create(tournament=tournament, team=self.team1)
        TournamentRegistration.objects.create(tournament=tournament, team=self.team2)

        # 1. Generierung erfolgreich
        TournamentBracketService.generate_bracket(tournament.id)
        tournament.refresh_from_db()
        self.assertTrue(tournament.is_generated)
        self.assertEqual(tournament.status, Tournament.Status.IN_PROGRESS)

        # 2. Zweite Generierung wird hart abgewiesen
        with self.assertRaises(BracketAlreadyGeneratedError):
            TournamentBracketService.generate_bracket(tournament.id)

        # 3. Reset ohne gespielte Matches funktioniert
        TournamentBracketService.reset_bracket(tournament.id)
        tournament.refresh_from_db()
        self.assertFalse(tournament.is_generated)
        self.assertEqual(tournament.status, Tournament.Status.REGISTRATION_OPEN)
        self.assertEqual(tournament.matches.count(), 0)

        # 4. Neu generieren, Match spielen und Reset sperren
        TournamentBracketService.generate_bracket(tournament.id)
        match = tournament.matches.first()
        match.status = TournamentMatch.Status.COMPLETED
        match.score_team1 = 16
        match.score_team2 = 10
        match.winner = self.team1
        match.save()

        # Reset ohne Force muss blockiert werden
        with self.assertRaises(TournamentBracketError):
            TournamentBracketService.reset_bracket(tournament.id, force=False)

    def test_match_scoring_hardening_and_winner_validation(self):
        """Punkt 5: Negative Scores werden abgelehnt, Widersprüche brauchen Begründung, Folge-Locks greifen."""
        from tournaments.exceptions import InvalidScoreError, InvalidWinnerError, MatchAlreadyCompletedError
        from tournaments.services import TournamentMatchService

        tournament = Tournament.objects.create(
            title="Scoring Test Cup",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            status=Tournament.Status.IN_PROGRESS,
            is_generated=True,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )

        final_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=2,
            match_number=1,
            status=TournamentMatch.Status.PENDING
        )

        semi_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            team1=self.team1,
            team2=self.team2,
            status=TournamentMatch.Status.READY,
            next_match_winner=final_match
        )

        # 1. Negativer Score wird abgewiesen
        with self.assertRaises(InvalidScoreError):
            TournamentMatchService.update_match_score(semi_match.id, score1=-5, score2=10)

        # 2. Score-Widerspruch ohne Begründung (Team 1 hat 16:0, aber Sieger soll Team 2 sein)
        with self.assertRaises(InvalidWinnerError):
            TournamentMatchService.update_match_score(
                semi_match.id,
                score1=16,
                score2=0,
                winner_id=self.team2.id,
                decision_reason=""
            )

        # 3. Score-Widerspruch mit Begründung (z.B. Disqualifikation) geht durch
        m, winner = TournamentMatchService.update_match_score(
            semi_match.id,
            score1=16,
            score2=0,
            winner_id=self.team2.id,
            decision_reason="Team Alpha wegen Cheating disqualifiziert"
        )
        self.assertEqual(winner, self.team2)
        m.refresh_from_db()
        self.assertEqual(m.winner, self.team2)
        self.assertEqual(m.decision_reason, "Team Alpha wegen Cheating disqualifiziert")

        # Folgematch hat nun team2 als team1
        final_match.refresh_from_db()
        self.assertEqual(final_match.team1, self.team2)

        # 4. Wenn das Folgematch beendet ist, darf semi_match nicht mehr modifiziert werden
        final_match.status = TournamentMatch.Status.COMPLETED
        final_match.save()

        with self.assertRaises(MatchAlreadyCompletedError):
            TournamentMatchService.update_match_score(semi_match.id, score1=16, score2=14)


class DoubleEliminationTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Double Elim Masters 2026",
            slug="de-masters-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="CS2 DE", mode="5v5", team_size=5)

    def _create_teams_and_tournament(self, num_teams):
        import secrets
        uid = secrets.token_hex(4)
        tournament = Tournament.objects.create(
            title=f"DE Tournament {num_teams} Teams {uid}",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        teams = []
        for i in range(1, num_teams + 1):
            user = User.objects.create_user(username=f"de_{uid}_{i}", email=f"de_{uid}_{i}@example.com", password="pass")
            team = Team.objects.create(name=f"Team {uid} {i}", captain=user, game=self.game, event=self.event)
            TeamMember.objects.create(team=team, user=user, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
            TournamentRegistration.objects.create(tournament=tournament, team=team)
            teams.append(team)
        return tournament, teams

    def test_bracket_structure_for_all_sizes(self):
        """
        Testet die algorithmische Bracket-Erzeugung für N = 2, 3, 4, 5, 6, 7, 8, 16.
        Prüft:
        - Exakte Anzahl an Loser-Bracket-Matches
        - Gesamtzahl aller Matches (2*BracketSize - 2)
        - Vollständige, fehlerfreie Verkettung (keine verwaisten oder fehlerhaften Ziellinks)
        """
        from tournaments.services import TournamentBracketService, next_power_of_two

        test_sizes = [2, 3, 4, 5, 6, 7, 8, 16]
        expected_lb_matches = {
            2: 0,
            4: 2,   # 1 in R1, 1 in R2
            8: 6,   # 2 in R1, 2 in R2, 1 in R3, 1 in R4
            16: 14  # 4 in R1, 4 in R2, 2 in R3, 2 in R4, 1 in R5, 1 in R6
        }

        for num_teams in test_sizes:
            tournament, teams = self._create_teams_and_tournament(num_teams)
            TournamentBracketService.generate_bracket(tournament.id)
            tournament.refresh_from_db()

            bracket_size = next_power_of_two(num_teams)
            expected_lb = expected_lb_matches[bracket_size]
            expected_wb = bracket_size - 1
            expected_total = expected_wb + expected_lb + 1  # +1 Grand Final

            all_matches = tournament.matches.all()
            wb_matches = all_matches.filter(bracket_type=TournamentMatch.BracketType.WINNERS)
            lb_matches = all_matches.filter(bracket_type=TournamentMatch.BracketType.LOSERS)
            gf_matches = all_matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)

            self.assertEqual(wb_matches.count(), expected_wb, f"N={num_teams}: WB Matches count mismatch")
            self.assertEqual(lb_matches.count(), expected_lb, f"N={num_teams}: LB Matches count mismatch")
            self.assertEqual(gf_matches.count(), 1, f"N={num_teams}: Grand Final count must be 1")
            self.assertEqual(all_matches.count(), expected_total, f"N={num_teams}: Total matches mismatch")

            # Verkettungs-Integritätsprüfung für jedes Match
            for m in all_matches:
                if m.next_match_winner:
                    self.assertEqual(m.next_match_winner.tournament_id, tournament.id)
                    self.assertIn(m.next_match_winner_slot, [1, 2])
                    self.assertNotEqual(m.next_match_winner_id, m.id)
                if m.next_match_loser:
                    self.assertEqual(m.next_match_loser.tournament_id, tournament.id)
                    self.assertIn(m.next_match_loser_slot, [1, 2])
                    self.assertNotEqual(m.next_match_loser_id, m.id)

    def test_double_elimination_two_teams_flow(self):
        """Sonderfall N = 2: Direkter Grand-Final-Pfad mit und ohne Bracket-Reset."""
        from tournaments.services import TournamentBracketService, TournamentMatchService

        # 1. Ohne Reset (WB Sieger gewinnt Grand Final direkt)
        t_no_reset, teams_no_reset = self._create_teams_and_tournament(2)
        TournamentBracketService.generate_bracket(t_no_reset.id)

        wb_match = t_no_reset.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS)
        gf_match = t_no_reset.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)

        self.assertEqual(wb_match.team1, teams_no_reset[0])
        self.assertEqual(wb_match.team2, teams_no_reset[1])

        # WB Match spielen: Team 1 gewinnt
        TournamentMatchService.update_match_score(wb_match.id, score1=16, score2=10)
        gf_match.refresh_from_db()
        self.assertEqual(gf_match.team1, teams_no_reset[0])
        self.assertEqual(gf_match.team2, teams_no_reset[1])
        self.assertEqual(gf_match.status, TournamentMatch.Status.READY)

        # Grand Final spielen: Team 1 gewinnt -> Turnier beendet, kein Reset
        TournamentMatchService.update_match_score(gf_match.id, score1=16, score2=12)
        t_no_reset.refresh_from_db()
        self.assertEqual(t_no_reset.status, Tournament.Status.FINISHED)
        self.assertEqual(t_no_reset.matches.count(), 2)

        # 2. Mit Reset (LB Sieger gewinnt Grand Final 1 -> Reset Match wird erzeugt)
        t_reset, teams_reset = self._create_teams_and_tournament(2)
        TournamentBracketService.generate_bracket(t_reset.id)

        wb_m2 = t_reset.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS)
        gf_m2 = t_reset.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL)

        # WB Match spielen: Team 1 gewinnt
        TournamentMatchService.update_match_score(wb_m2.id, score1=16, score2=10)
        gf_m2.refresh_from_db()

        # Grand Final 1 spielen: Team 2 (Verlierer aus WB) gewinnt!
        TournamentMatchService.update_match_score(gf_m2.id, score1=10, score2=16)

        # Reset Match prüfen
        reset_match = t_reset.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).first()
        self.assertIsNotNone(reset_match)
        self.assertEqual(reset_match.status, TournamentMatch.Status.READY)
        self.assertEqual(reset_match.team1, teams_reset[0])
        self.assertEqual(reset_match.team2, teams_reset[1])

        # Reset Match spielen: Team 2 gewinnt das Turnier
        TournamentMatchService.update_match_score(reset_match.id, score1=10, score2=16)
        t_reset.refresh_from_db()
        self.assertEqual(t_reset.status, Tournament.Status.FINISHED)
        self.assertEqual(t_reset.matches.count(), 3)

    def test_double_elimination_four_teams_full_tournament_no_reset(self):
        """Vollständiger Turnierablauf für N=4 Teams: WB-Sieger gewinnt das Grand Final direkt."""
        from tournaments.services import TournamentBracketService, TournamentMatchService

        tournament, teams = self._create_teams_and_tournament(4)
        t1, t2, t3, t4 = teams[0], teams[1], teams[2], teams[3]

        TournamentBracketService.generate_bracket(tournament.id)

        wb_r1_m1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=1)
        wb_r1_m2 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=2)
        wb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=2, match_number=1)
        lb_r1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=1, match_number=1)
        lb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=2, match_number=1)
        grand_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL, round_number=1, match_number=1)

        # 1. WB R1: T1 schlägt T4, T2 schlägt T3 (gemäß Standard-Seeding (1,4), (2,3))
        TournamentMatchService.update_match_score(wb_r1_m1.id, score1=16, score2=5)  # T1 siegt
        TournamentMatchService.update_match_score(wb_r1_m2.id, score1=16, score2=8)  # T2 siegt

        wb_final.refresh_from_db()
        lb_r1.refresh_from_db()

        self.assertEqual(wb_final.team1, t1)
        self.assertEqual(wb_final.team2, t2)
        self.assertEqual(wb_final.status, TournamentMatch.Status.READY)

        self.assertEqual(lb_r1.team1, t4)
        self.assertEqual(lb_r1.team2, t3)
        self.assertEqual(lb_r1.status, TournamentMatch.Status.READY)

        # 2. LB R1: T3 schlägt T4 (T4 scheidet aus)
        TournamentMatchService.update_match_score(lb_r1.id, score1=10, score2=16)

        # 3. WB Final: T1 schlägt T2 (T1 -> Grand Final, T2 -> LB Final)
        TournamentMatchService.update_match_score(wb_final.id, score1=16, score2=12)

        lb_final.refresh_from_db()
        self.assertEqual(lb_final.team1, t3)  # Sieger aus LB R1
        self.assertEqual(lb_final.team2, t2)  # Verlierer aus WB Final
        self.assertEqual(lb_final.status, TournamentMatch.Status.READY)

        # 4. LB Final: T3 schlägt T2 (T3 -> Grand Final, T2 scheidet als 3. Platz aus)
        TournamentMatchService.update_match_score(lb_final.id, score1=16, score2=14)

        grand_final.refresh_from_db()
        self.assertEqual(grand_final.team1, t1)  # WB Sieger
        self.assertEqual(grand_final.team2, t3)  # LB Sieger
        self.assertEqual(grand_final.status, TournamentMatch.Status.READY)

        # 5. Grand Final: T1 schlägt T3 direkt
        TournamentMatchService.update_match_score(grand_final.id, score1=16, score2=9)

        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)
        self.assertFalse(tournament.matches.filter(bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET).exists())

    def test_double_elimination_bye_handling_three_teams(self):
        """BYE-Handling: 3 Teams auf 4er-Bracket -> BYE erzeugt keinen Geister-Verlierer im LB."""
        from tournaments.services import TournamentBracketService, TournamentMatchService

        tournament, teams = self._create_teams_and_tournament(3)
        t1, t2, t3 = teams[0], teams[1], teams[2]

        TournamentBracketService.generate_bracket(tournament.id)

        wb_r1_m1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=1)
        wb_r1_m2 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=2)
        wb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=2, match_number=1)
        lb_r1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=1, match_number=1)
        lb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=2, match_number=1)

        # WB R1 M1 ist Freilos für T1
        self.assertTrue(wb_r1_m1.is_bye)
        self.assertEqual(wb_r1_m1.winner, t1)
        self.assertIsNone(wb_r1_m1.loser)

        # T1 steht bereits im WB Final
        wb_final.refresh_from_db()
        self.assertEqual(wb_final.team1, t1)

        # WB R1 M2 spielen: T2 schlägt T3 (T3 fällt ins LB)
        TournamentMatchService.update_match_score(wb_r1_m2.id, score1=16, score2=11)

        # Da WB R1 M1 ein BYE war, rückt T3 aus LB R1 automatisch per Freilos ins LB Finale vor
        lb_r1.refresh_from_db()
        self.assertTrue(lb_r1.is_bye)
        self.assertEqual(lb_r1.winner, t3)

        lb_final.refresh_from_db()
        self.assertEqual(lb_final.team1, t3)

    def test_double_elimination_wb_played_before_lb_does_not_grant_premature_bye(self):
        """
        Kritischer Bugfix: Wenn alle WB-Matches vor den LB-Matches gespielt werden,
        darf das LB-Finale NICHT vorzeitig als Freilos gewertet werden, während
        das LB-Vorgängermatch noch offen ist.
        """
        from tournaments.services import TournamentBracketService, TournamentMatchService

        tournament, teams = self._create_teams_and_tournament(4)
        t1, t2, t3, t4 = teams[0], teams[1], teams[2], teams[3]

        TournamentBracketService.generate_bracket(tournament.id)

        wb_r1_m1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=1)
        wb_r1_m2 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=2)
        wb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=2, match_number=1)
        lb_r1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=1, match_number=1)
        lb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=2, match_number=1)
        grand_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL, round_number=1, match_number=1)

        # 1. WB R1: T1 schlägt T4, T2 schlägt T3
        TournamentMatchService.update_match_score(wb_r1_m1.id, score1=16, score2=5)
        TournamentMatchService.update_match_score(wb_r1_m2.id, score1=16, score2=8)

        # 2. WB Final wird VOR LB R1 gespielt: T1 schlägt T2
        TournamentMatchService.update_match_score(wb_final.id, score1=16, score2=12)

        lb_final.refresh_from_db()
        grand_final.refresh_from_db()
        lb_r1.refresh_from_db()

        # LB R1 muss nach wie vor READY sein (T4 vs T3)
        self.assertEqual(lb_r1.status, TournamentMatch.Status.READY)
        self.assertEqual(lb_r1.team1, t4)
        self.assertEqual(lb_r1.team2, t3)
        self.assertFalse(lb_r1.is_bye)

        # LB Finale darf KEIN Freilos sein und muss auf Sieger aus LB R1 warten!
        self.assertEqual(lb_final.status, TournamentMatch.Status.PENDING)
        self.assertFalse(lb_final.is_bye)
        self.assertIsNone(lb_final.team1)
        self.assertEqual(lb_final.team2, t2)
        self.assertIsNone(lb_final.winner)

        # Grand Final darf T2 NICHT als Gegner enthalten
        self.assertEqual(grand_final.team1, t1)
        self.assertIsNone(grand_final.team2)
        self.assertEqual(grand_final.status, TournamentMatch.Status.PENDING)

        # 3. Nun wird LB R1 gespielt: T3 schlägt T4
        TournamentMatchService.update_match_score(lb_r1.id, score1=10, score2=16)

        lb_final.refresh_from_db()
        self.assertEqual(lb_final.team1, t3)
        self.assertEqual(lb_final.team2, t2)
        self.assertEqual(lb_final.status, TournamentMatch.Status.READY)

        # 4. Nun wird LB Final gespielt: T3 schlägt T2
        TournamentMatchService.update_match_score(lb_final.id, score1=16, score2=14)

        grand_final.refresh_from_db()
        self.assertEqual(grand_final.team1, t1)
        self.assertEqual(grand_final.team2, t3)
        self.assertEqual(grand_final.status, TournamentMatch.Status.READY)

        # 5. Grand Final: T1 schlägt T3
        TournamentMatchService.update_match_score(grand_final.id, score1=16, score2=11)
        tournament.refresh_from_db()
        self.assertEqual(tournament.status, Tournament.Status.FINISHED)

    def test_double_elimination_bye_handling_three_teams_wb_final_early(self):
        """
        BYE-Handling mit 3 Teams: WB Final wird vor dem LB-Match gespielt.
        Es darf zu keiner vorzeitigen Freilos-Vergabe im LB Final kommen.
        """
        from tournaments.services import TournamentBracketService, TournamentMatchService

        tournament, teams = self._create_teams_and_tournament(3)
        t1, t2, t3 = teams[0], teams[1], teams[2]

        TournamentBracketService.generate_bracket(tournament.id)

        wb_r1_m1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=1)
        wb_r1_m2 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=1, match_number=2)
        wb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.WINNERS, round_number=2, match_number=1)
        lb_r1 = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=1, match_number=1)
        lb_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.LOSERS, round_number=2, match_number=1)
        grand_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL, round_number=1, match_number=1)

        # WB R1 M1 ist Freilos für T1
        self.assertTrue(wb_r1_m1.is_bye)
        self.assertEqual(wb_r1_m1.winner, t1)

        # T1 steht im WB Final
        wb_final.refresh_from_db()
        self.assertEqual(wb_final.team1, t1)

        # WB R1 M2 spielen: T2 schlägt T3
        TournamentMatchService.update_match_score(wb_r1_m2.id, score1=16, score2=11)

        # T3 rückt per BYE in LB Final vor (Slot 1)
        lb_r1.refresh_from_db()
        self.assertTrue(lb_r1.is_bye)
        self.assertEqual(lb_r1.winner, t3)

        lb_final.refresh_from_db()
        self.assertEqual(lb_final.team1, t3)
        self.assertIsNone(lb_final.team2)
        self.assertEqual(lb_final.status, TournamentMatch.Status.PENDING)

        # WB Final spielen: T1 schlägt T2 (T2 fällt in LB Final Slot 2)
        TournamentMatchService.update_match_score(wb_final.id, score1=16, score2=12)

        lb_final.refresh_from_db()
        self.assertEqual(lb_final.team1, t3)
        self.assertEqual(lb_final.team2, t2)
        self.assertEqual(lb_final.status, TournamentMatch.Status.READY)

        # LB Final spielen: T2 schlägt T3 (T2 -> Grand Final)
        TournamentMatchService.update_match_score(lb_final.id, score1=10, score2=16)

        grand_final.refresh_from_db()
        self.assertEqual(grand_final.team1, t1)
        self.assertEqual(grand_final.team2, t2)
        self.assertEqual(grand_final.status, TournamentMatch.Status.READY)

    def test_double_elimination_multi_bye_cascade_eight_teams(self):
        """
        Double Elimination mit 5 Teams auf 8er-Bracket (3 BYEs).
        Prüft deterministische Kaskadierung von Freilosen im Loser Bracket
        auch bei variierenden Spielreihenfolgen.
        """
        from tournaments.services import TournamentBracketService, TournamentMatchService

        tournament, teams = self._create_teams_and_tournament(5)
        TournamentBracketService.generate_bracket(tournament.id)

        # Alle WB R1 Matches prüfen
        wb_r1_matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            round_number=1
        ).order_by('match_number')

        bye_matches = wb_r1_matches.filter(is_bye=True)
        self.assertEqual(bye_matches.count(), 3)
        real_matches = wb_r1_matches.filter(is_bye=False)
        self.assertEqual(real_matches.count(), 1)

        # Das reguläre Match spielen
        real_match = real_matches.first()
        self.assertEqual(real_match.status, TournamentMatch.Status.READY)
        TournamentMatchService.update_match_score(real_match.id, score1=16, score2=8)

        # Jetzt alle weiteren WB Matches nacheinander abwickeln
        wb_r2_matches = tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            round_number=2
        ).order_by('match_number')

        for m in wb_r2_matches:
            m.refresh_from_db()
            self.assertEqual(m.status, TournamentMatch.Status.READY)
            TournamentMatchService.update_match_score(m.id, score1=16, score2=10)

        # WB Final spielen
        wb_final = tournament.matches.get(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            round_number=3,
            match_number=1
        )
        TournamentMatchService.update_match_score(wb_final.id, score1=16, score2=12)

        # Zu diesem Zeitpunkt darf das Grand Final NOCH NICHT voll besetzt sein
        grand_final = tournament.matches.get(bracket_type=TournamentMatch.BracketType.GRAND_FINAL, round_number=1, match_number=1)
        grand_final.refresh_from_db()
        self.assertIsNotNone(grand_final.team1)
        self.assertIsNone(grand_final.team2)
        self.assertEqual(grand_final.status, TournamentMatch.Status.PENDING)


class TournamentFrontendRegistrationFlowTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Frontend Test LAN",
            slug="frontend-test-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game_solo = Game.objects.create(name="TrackMania 1v1", mode="1v1", team_size=1)
        self.game_team = Game.objects.create(name="Valorant 5v5", mode="5v5", team_size=5)

        self.tournament_solo = Tournament.objects.create(
            title="TM Solo Cup",
            slug="tm-solo-cup",
            event=self.event,
            game=self.game_solo,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        self.tournament_team = Tournament.objects.create(
            title="Valorant Championship",
            slug="valorant-championship",
            event=self.event,
            game=self.game_team,
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(hours=1),
            registration_end=timezone.now() + timedelta(hours=1),
        )
        self.user = User.objects.create_user(username="test_guest", email="guest@example.com", password="password")
        self.staff_user = User.objects.create_user(username="test_staff", email="staff@example.com", password="password", is_staff=True)

    def test_unauthenticated_user_sees_login_prompt(self):
        """Nicht eingeloggte Gäste sehen einen Login-Link und nicht die Einlass-Warnung."""
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_solo.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bitte anmelden")
        self.assertContains(response, "Login")
        self.assertNotContains(response, "bist aber noch nicht am Einlass eingecheckt")

    def test_authenticated_user_without_ticket_sees_ticket_prompt(self):
        """Eingeloggte Benutzer ohne Ticket sehen die Aufforderung, sich ein Ticket zu sichern."""
        self.client.login(username="test_guest", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_solo.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket für")
        self.assertContains(response, "Ticket holen")

    def test_authenticated_user_with_ticket_not_checked_in_sees_warning(self):
        """Eingeloggte Benutzer mit Ticket, die noch nicht eingecheckt sind, sehen den Einlass-Hinweis."""
        EventRegistration.objects.create(user=self.user, event=self.event, is_checked_in=False)
        self.client.login(username="test_guest", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_solo.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "noch nicht am Einlass eingecheckt")

    def test_checked_in_user_without_team_sees_team_search_button(self):
        """Eingecheckte Benutzer ohne Team für ein Team-Turnier sehen den Button 'Zur Teamsuche'."""
        EventRegistration.objects.create(user=self.user, event=self.event, is_checked_in=True)
        self.client.login(username="test_guest", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_team.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Zur Teamsuche")
        self.assertContains(response, "Du bist aktuell in keinem Team für Valorant 5v5")

    def test_checked_in_user_with_team_sees_dropdown_and_team_search(self):
        """Eingecheckte Benutzer mit passendem Team sehen das Auswahl-Dropdown und den 'Zur Teamsuche'-Link."""
        EventRegistration.objects.create(user=self.user, event=self.event, is_checked_in=True)
        team = Team.objects.create(name="Team Phoenix", captain=self.user, game=self.game_team, event=self.event)
        TeamMember.objects.create(team=team, user=self.user, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.client.login(username="test_guest", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_team.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team Phoenix")
        self.assertContains(response, "Team anmelden")
        self.assertContains(response, "Zur Teamsuche")

    def test_checked_in_user_solo_game_sees_one_click_register(self):
        """In 1v1-Turnieren sieht der eingecheckte Benutzer den 1-Click-Anmeldebutton."""
        EventRegistration.objects.create(user=self.user, event=self.event, is_checked_in=True)
        self.client.login(username="test_guest", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament_solo.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jetzt als Einzelspieler anmelden (1-Click)")

    def test_staff_user_can_register_without_prior_checkin(self):
        """Staff-Benutzer können sich und Test-Teams auch ohne Vor-Ort-Checkin anmelden."""
        self.client.login(username="test_staff", password="password")
        response = self.client.post(reverse('tournament_register', kwargs={'slug': self.tournament_solo.slug}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TournamentRegistration.objects.filter(tournament=self.tournament_solo).exists())
        self.assertContains(response, "erfolgreich für")


class GroupStageTournamentTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Group Stage LAN",
            slug="group-stage-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="CS2", mode="5v5", team_size=5)
        self.tournament_4 = Tournament.objects.create(
            title="Group 4 Teams",
            slug="group-4-teams",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.GROUP_STAGE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=4,
        )
        self.tournament_8 = Tournament.objects.create(
            title="Group 8 Teams",
            slug="group-8-teams",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.GROUP_STAGE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=8,
        )
        self.teams = []
        for i in range(1, 9):
            user = User.objects.create_user(username=f"g_player_{i}", password="pass")
            team = Team.objects.create(name=f"Group Team {i}", captain=user, game=self.game, event=self.event)
            self.teams.append(team)

    def test_group_stage_4_teams_flow(self):
        """4 Teams: 2 Gruppen à 2 Teams -> Gruppenspiele -> automatisches Finale -> Turniersieger."""
        for t in self.teams[:4]:
            TournamentRegistration.objects.create(tournament=self.tournament_4, team=t)

        generate_bracket(self.tournament_4)
        self.assertTrue(self.tournament_4.is_generated)

        # 2 Gruppen à 1 Match + 1 Final-Match
        group_matches = self.tournament_4.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        final_match = self.tournament_4.matches.get(bracket_type=TournamentMatch.BracketType.FINAL)

        self.assertEqual(group_matches.count(), 2)
        self.assertEqual(final_match.status, TournamentMatch.Status.PENDING)

        # Spiele Gruppe A Match: Team 1 gewinnt gegen Team 3
        match_a = group_matches.get(group_name='Gruppe A')
        TournamentMatchService.update_match_score(match_a.id, score1=16, score2=5, winner_id=match_a.team1_id)

        # Finalmatch noch pending weil Gruppe B noch nicht gespielt
        final_match.refresh_from_db()
        self.assertEqual(final_match.status, TournamentMatch.Status.PENDING)

        # Spiele Gruppe B Match: Team 2 gewinnt gegen Team 4
        match_b = group_matches.get(group_name='Gruppe B')
        TournamentMatchService.update_match_score(match_b.id, score1=16, score2=10, winner_id=match_b.team1_id)

        # Finale sollte jetzt READY sein mit Team 1 und Team 2
        final_match.refresh_from_db()
        self.assertEqual(final_match.status, TournamentMatch.Status.READY)
        self.assertEqual(final_match.team1, match_a.team1)
        self.assertEqual(final_match.team2, match_b.team1)

        # Finale spielen -> Turnier FINISHED
        TournamentMatchService.update_match_score(final_match.id, score1=2, score2=1, winner_id=final_match.team1_id)
        self.tournament_4.refresh_from_db()
        self.assertEqual(self.tournament_4.status, Tournament.Status.FINISHED)

    def test_group_stage_8_teams_flow_with_semifinals(self):
        """8 Teams: 2 Gruppen à 4 Teams -> 12 Gruppenspiele -> Halbfinals (A1 vs B2, B1 vs A2) -> Finale."""
        for t in self.teams:
            TournamentRegistration.objects.create(tournament=self.tournament_8, team=t)

        generate_bracket(self.tournament_8)

        # Gruppe A & B haben je 6 Matches (4 Teams Round Robin = 6) = 12 Matches
        group_matches = self.tournament_8.matches.filter(bracket_type=TournamentMatch.BracketType.GROUP)
        self.assertEqual(group_matches.count(), 12)

        semis = list(self.tournament_8.matches.filter(bracket_type=TournamentMatch.BracketType.FINAL, round_number=2).order_by('match_number'))
        self.assertEqual(len(semis), 2)

        final = self.tournament_8.matches.get(bracket_type=TournamentMatch.BracketType.FINAL, round_number=3)
        self.assertEqual(final.status, TournamentMatch.Status.PENDING)

        # Alle Gruppenspiele simulieren
        for m in group_matches:
            TournamentMatchService.update_match_score(m.id, score1=16, score2=5, winner_id=m.team1_id)

        # Nach Abschluss aller Gruppenspiele sollten Halbfinals READY sein
        for s in semis:
            s.refresh_from_db()
            self.assertEqual(s.status, TournamentMatch.Status.READY)
            self.assertIsNotNone(s.team1)
            self.assertIsNotNone(s.team2)

        # Halbfinals spielen
        s1 = semis[0]
        s2 = semis[1]
        TournamentMatchService.update_match_score(s1.id, score1=16, score2=10, winner_id=s1.team1_id)
        TournamentMatchService.update_match_score(s2.id, score1=16, score2=12, winner_id=s2.team1_id)

        # Finale sollte jetzt READY sein
        final.refresh_from_db()
        self.assertEqual(final.status, TournamentMatch.Status.READY)
        self.assertEqual(final.team1, s1.team1)
        self.assertEqual(final.team2, s2.team1)

        # Finale spielen -> Turnier FINISHED
        TournamentMatchService.update_match_score(final.id, score1=16, score2=14, winner_id=final.team1_id)
        self.tournament_8.refresh_from_db()
        self.assertEqual(self.tournament_8.status, Tournament.Status.FINISHED)


class LeagueTournamentTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="League LAN",
            slug="league-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Rocket League", mode="3v3", team_size=3)
        self.tournament = Tournament.objects.create(
            title="Rocket League Season 1",
            slug="rocket-league-s1",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.LEAGUE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=4,
        )
        self.teams = []
        for i in range(1, 5):
            user = User.objects.create_user(username=f"l_player_{i}", password="pass")
            team = Team.objects.create(name=f"League Team {i}", captain=user, game=self.game, event=self.event)
            self.teams.append(team)
            TournamentRegistration.objects.create(tournament=self.tournament, team=team)

    def test_league_generation_and_standings(self):
        """Berger-System Spielplan-Generierung, Punkteberechnung, Tiebreaks und Auto-Abschluss."""
        generate_bracket(self.tournament)
        matches = self.tournament.matches.all()
        # 4 Teams = 3 Runden à 2 Matches = 6 Matches
        self.assertEqual(matches.count(), 6)

        # Initial Standings alle 0 Punkte
        standings = LeagueStandingService.calculate_league_standings(self.tournament)
        self.assertEqual(len(standings), 4)
        self.assertEqual(standings[0]['points'], 0)

        # Runde 1 spielen
        r1_matches = matches.filter(round_number=1)
        for m in r1_matches:
            TournamentMatchService.update_match_score(m.id, score1=3, score2=1, winner_id=m.team1_id)

        standings = LeagueStandingService.calculate_league_standings(self.tournament)
        # Die beiden Sieger haben je 3 Punkte
        self.assertEqual(standings[0]['points'], 3)
        self.assertEqual(standings[1]['points'], 3)

        # Restliche Runden spielen
        for m in matches.exclude(round_number=1):
            TournamentMatchService.update_match_score(m.id, score1=3, score2=0, winner_id=m.team1_id)

        # Turnier sollte automatisch FINISHED sein
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.FINISHED)

        final_standings = LeagueStandingService.calculate_league_standings(self.tournament)
        self.assertEqual(final_standings[0]['rank'], 1)
        self.assertTrue(final_standings[0]['points'] > 0)


class FFATournamentTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="FFA LAN",
            slug="ffa-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Trackmania", mode="Solo FFA", team_size=1)
        self.tournament = Tournament.objects.create(
            title="Trackmania Grand Prix",
            slug="trackmania-grand-prix",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.FFA,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=6,
        )
        self.teams = []
        for i in range(1, 7):
            user = User.objects.create_user(username=f"tm_driver_{i}", password="pass")
            team = Team.objects.create(name=f"Driver {i}", captain=user, game=self.game, event=self.event, is_solo=True)
            self.teams.append(team)
            TournamentRegistration.objects.create(tournament=self.tournament, team=team)

    def test_ffa_generation_and_result_recording(self):
        """FFA Generierung mit TournamentMatchParticipant, Multi-Ergebniseingabe und Siegerermittlung."""
        generate_bracket(self.tournament)
        match = self.tournament.matches.get(bracket_type=TournamentMatch.BracketType.FFA)
        participants = list(match.participants.all())
        self.assertEqual(len(participants), 6)

        # Ergebnisse eintragen
        participant_scores = []
        for idx, p in enumerate(participants, 1):
            participant_scores.append({
                'participant_id': p.id,
                'rank': idx,
                'score': 100 - (idx * 10),
                'notes': f"Runde {idx} abgeschlossen",
            })

        FFAMatchService.update_ffa_scores(match.id, participant_scores)

        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(match.winner, participants[0].team)

        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.FINISHED)

        p1 = match.participants.get(rank=1)
        self.assertEqual(p1.score, 90)
        self.assertEqual(p1.team, participants[0].team)


class TeamFeedbackAndIntegrityTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Integrity LAN",
            slug="integrity-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.other_event = Event.objects.create(
            title="Past LAN 2025",
            slug="past-lan-2025",
            is_active=False,
            start_date=timezone.now() - timedelta(days=365),
            end_date=timezone.now() - timedelta(days=363),
        )
        self.game = Game.objects.create(name="Valorant", mode="5v5", team_size=5)
        self.other_game = Game.objects.create(name="CS2", mode="5v5", team_size=5)

        self.captain = User.objects.create_user(username="cap_val", password="password")
        self.player2 = User.objects.create_user(username="p2_val", password="password")
        self.player3 = User.objects.create_user(username="p3_val", password="password")
        self.player4 = User.objects.create_user(username="p4_val", password="password")
        self.player5 = User.objects.create_user(username="p5_val", password="password")

        # Check-in for event
        EventRegistration.objects.create(user=self.captain, event=self.event, is_checked_in=True)
        EventRegistration.objects.create(user=self.player2, event=self.event, is_checked_in=True)
        EventRegistration.objects.create(user=self.player3, event=self.event, is_checked_in=True)
        EventRegistration.objects.create(user=self.player4, event=self.event, is_checked_in=True)
        EventRegistration.objects.create(user=self.player5, event=self.event, is_checked_in=True)

        self.team = Team.objects.create(
            name="Valorant Prime",
            captain=self.captain,
            game=self.game,
            event=self.event,
        )
        for u in [self.captain, self.player2, self.player3, self.player4, self.player5]:
            TeamMember.objects.create(
                team=self.team,
                user=u,
                role=TeamMember.Role.CAPTAIN if u == self.captain else TeamMember.Role.MEMBER,
                status=TeamMember.Status.ACCEPTED
            )

        self.tournament = Tournament.objects.create(
            title="Valorant Championship",
            slug="val-champ",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=8,
        )

    def test_join_team_by_code_accepts_pending_application(self):
        """Ausstehende PENDING-Bewerbungen werden bei Eingabe des korrekten Einladungscodes auf ACCEPTED gesetzt."""
        TeamMember.objects.filter(team=self.team, user=self.player5).delete()
        applicant = User.objects.create_user(username="applicant_val", password="password")
        # 1. Apply to team
        membership = TeamMember.objects.create(
            team=self.team,
            user=applicant,
            role=TeamMember.Role.MEMBER,
            status=TeamMember.Status.PENDING
        )
        self.assertEqual(membership.status, TeamMember.Status.PENDING)

        # 2. Join by code
        self.client.login(username="applicant_val", password="password")
        response = self.client.post(reverse('team_join_by_code'), {'invite_code': self.team.invite_code}, follow=True)
        self.assertEqual(response.status_code, 200)

        membership.refresh_from_db()
        self.assertEqual(membership.status, TeamMember.Status.ACCEPTED)
        self.assertContains(response, "erfolgreich beigetreten")

        # Roster wiederherstellen
        membership.delete()
        TeamMember.objects.create(team=self.team, user=self.player5, status=TeamMember.Status.ACCEPTED)

    def test_team_registration_validation_rules(self):
        """Umfassende Prüfung der Validierungsregeln für Team-Turnieranmeldungen."""
        # 1. Archiviertes Team wird abgelehnt
        self.team.is_archived = True
        self.team.save()
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("archiviert", str(cm.exception))
        self.team.is_archived = False
        self.team.save()

        # 2. Team aus anderem Event wird abgelehnt
        self.team.event = self.other_event
        self.team.save()
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("Veranstaltung", str(cm.exception))
        self.team.event = self.event
        self.team.save()

        # 3. Team mit falschem Spiel wird abgelehnt
        self.team.game = self.other_game
        self.team.save()
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("registriert, das Turnier ist jedoch für", str(cm.exception))

        # 3b. Team ohne Spiel wird abgelehnt
        self.team.game = None
        self.team.save()
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("kein Spiel zugeordnet", str(cm.exception))
        self.team.game = self.game
        self.team.save()

        # 4. Nicht-Kapitän versucht anzumelden wird abgelehnt
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.player2, self.team.id)
        self.assertIn("Nur der Kapitän", str(cm.exception))

        # 5. Team mit zu wenigen Mitgliedern (< 5) wird abgelehnt
        m5 = TeamMember.objects.get(team=self.team, user=self.player5)
        m5.delete()
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("erforderlichen Mitgliedern", str(cm.exception))
        TeamMember.objects.create(team=self.team, user=self.player5, status=TeamMember.Status.ACCEPTED)

        # 5b. Team mit zu vielen Mitgliedern (> 5) wird abgelehnt
        player6 = User.objects.create_user(username="p6_val", password="password")
        EventRegistration.objects.create(user=player6, event=self.event, is_checked_in=True)
        m6 = TeamMember.objects.create(team=self.team, user=player6, status=TeamMember.Status.ACCEPTED)
        with self.assertRaises(TournamentRegistrationError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("maximal 5 Spieler erlaubt", str(cm.exception))
        m6.delete()
        player6.delete()

        # 6. Teammitglied nicht eingecheckt wird abgelehnt
        reg5 = EventRegistration.objects.get(user=self.player5, event=self.event)
        reg5.is_checked_in = False
        reg5.save()
        with self.assertRaises(TournamentNotCheckedInError) as cm:
            TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertIn("nicht am Einlass", str(cm.exception))
        reg5.is_checked_in = True
        reg5.save()

        # 7. Valides Team kann erfolgreich angemeldet werden
        reg, created = TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        self.assertTrue(created)
        self.assertEqual(reg.team, self.team)

    def test_team_integrity_protection_during_active_tournament(self):
        """Teams in aktiven Turnieren können nicht gelöscht oder während des Turniers aufgelöst werden."""
        # Zweites Team für Turnier erstellen
        cap2 = User.objects.create_user(username="cap2_val", password="password")
        EventRegistration.objects.create(user=cap2, event=self.event, is_checked_in=True)
        team2 = Team.objects.create(name="Opponent 5v5", captain=cap2, game=self.game, event=self.event)
        TeamMember.objects.create(team=team2, user=cap2, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        for i in range(2, 6):
            p = User.objects.create_user(username=f"opp_p{i}", password="password")
            EventRegistration.objects.create(user=p, event=self.event, is_checked_in=True)
            TeamMember.objects.create(team=team2, user=p, status=TeamMember.Status.ACCEPTED)

        TournamentRegistrationService.register_team(self.tournament.id, self.captain, self.team.id)
        TournamentRegistrationService.register_team(self.tournament.id, cap2, team2.id)

        generate_bracket(self.tournament)
        self.assertTrue(self.tournament.is_generated)
        self.assertTrue(self.team.is_in_active_tournament())

        # 1. Löschen der Instanz wirft ValidationError
        with self.assertRaises(ValidationError):
            self.team.delete()

        # 2. Kick von Mitgliedern während aktivem Turnier blockiert
        self.client.login(username="cap_val", password="password")
        response = self.client.post(
            reverse('team_kick_member', kwargs={'slug': self.team.slug, 'user_id': self.player2.id}),
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(TeamMember.objects.filter(team=self.team, user=self.player2).exists())
        self.assertContains(response, "während eines laufenden Turniers nicht")

        # 3. Letztes Mitglied kann Team nicht verlassen / auflösen
        # Entferne 4 Mitglieder direkt (Simulation Notfall)
        TeamMember.objects.filter(team=self.team, user__in=[self.player2, self.player3, self.player4, self.player5]).delete()
        res = self.team.leave_team(self.captain)
        self.assertEqual(res, 'in_active_tournament')
        self.assertTrue(Team.objects.filter(id=self.team.id).exists())

    def test_forfeit_and_walkover_on_forced_team_delete_during_tournament(self):
        """Wenn ein Team mit force=True gelöscht oder zurückgezogen wird, erhält der Gegner ein Freilos/Walkover."""
        cap1 = User.objects.create_user(username="cap_fo1", password="password")
        EventRegistration.objects.create(user=cap1, event=self.event, is_checked_in=True)
        team1 = Team.objects.create(name="Team 1", captain=cap1, game=self.game, event=self.event)
        TeamMember.objects.create(team=team1, user=cap1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        for i in range(2, 6):
            p = User.objects.create_user(username=f"fo1_p{i}", password="password")
            EventRegistration.objects.create(user=p, event=self.event, is_checked_in=True)
            TeamMember.objects.create(team=team1, user=p, status=TeamMember.Status.ACCEPTED)

        cap2 = User.objects.create_user(username="cap_fo2", password="password")
        EventRegistration.objects.create(user=cap2, event=self.event, is_checked_in=True)
        team2 = Team.objects.create(name="Team 2", captain=cap2, game=self.game, event=self.event)
        TeamMember.objects.create(team=team2, user=cap2, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        for i in range(2, 6):
            p = User.objects.create_user(username=f"fo2_p{i}", password="password")
            EventRegistration.objects.create(user=p, event=self.event, is_checked_in=True)
            TeamMember.objects.create(team=team2, user=p, status=TeamMember.Status.ACCEPTED)

        TournamentRegistrationService.register_team(self.tournament.id, cap1, team1.id)
        TournamentRegistrationService.register_team(self.tournament.id, cap2, team2.id)

        generate_bracket(self.tournament)

        match = TournamentMatch.objects.filter(tournament=self.tournament, team1=team1, team2=team2).first()
        self.assertIsNotNone(match)
        self.assertEqual(match.status, TournamentMatch.Status.READY)

        # Team 1 wird forciert gelöscht (z. B. Admin-Eingriff oder Disqualifikation)
        team1.delete(force=True)

        # Match muss als COMPLETED gewertet sein, Sieger ist Team 2
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(match.winner, team2)
        self.assertIn("Walkover", match.decision_reason)

    def test_solo_team_leave_team_with_force_forfeit(self):
        """Ein Solo-Spieler kann sein Team mit force_forfeit=True verlassen; der Gegner gewinnt kampflos."""
        solo_game = Game.objects.create(name="1v1 Starcraft", team_size=1)
        tournament_1v1 = Tournament.objects.create(
            title="SC 1v1 Cup",
            game=solo_game,
            event=self.event,
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            is_generated=False,
            max_teams=4,
            registration_start=timezone.now() - timezone.timedelta(hours=1),
            registration_end=timezone.now() + timezone.timedelta(hours=2),
        )

        solo_cap = User.objects.create_user(username="solo_runner", password="password")
        EventRegistration.objects.create(user=solo_cap, event=self.event, is_checked_in=True)
        solo_team = Team.objects.create(name="Solo Runner", captain=solo_cap, game=solo_game, event=self.event, is_solo=True)
        TeamMember.objects.create(team=solo_team, user=solo_cap, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        opp_cap = User.objects.create_user(username="opp_runner", password="password")
        EventRegistration.objects.create(user=opp_cap, event=self.event, is_checked_in=True)
        opp_team = Team.objects.create(name="Opp Runner", captain=opp_cap, game=solo_game, event=self.event, is_solo=True)
        TeamMember.objects.create(team=opp_team, user=opp_cap, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        TournamentRegistrationService.register_team(tournament_1v1.id, solo_cap, solo_team.id)
        TournamentRegistrationService.register_team(tournament_1v1.id, opp_cap, opp_team.id)

        generate_bracket(tournament_1v1)

        match = TournamentMatch.objects.filter(tournament=tournament_1v1, team1=solo_team, team2=opp_team).first()
        self.assertIsNotNone(match)

        res = solo_team.leave_team(solo_cap, force_forfeit=True)
        self.assertEqual(res, 'deleted')

        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(match.winner, opp_team)

    def test_tournament_detail_inline_bracket_and_score_validation(self):
        """Turnieransicht nutzt Inline-Bestätigung zur Bracket-Generierung und Inline-Fehleranzeige für Scores."""
        staff_admin = User.objects.create_user(username="staff_admin_test", password="password", is_staff=True)
        self.client.login(username="staff_admin_test", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Inline Bracket-Generierung
        self.assertIn('id="bracket-generate-confirm"', content)
        self.assertIn('toggleGenerateBracketConfirm', content)
        # Inline Fehleranzeige & Validierung für Matchergebnisse
        self.assertIn('id="scoreFormError"', content)
        self.assertIn('checkTieWarning', content)
        # Keine Browser-Dialoge
        self.assertNotIn('confirm(', content)
        self.assertNotIn('alert(', content)

    def test_team_detail_inline_leave_and_kick(self):
        """Team-Detailansicht nutzt moderne Inline-Bestätigungen für Team-Verlassen und Kicken."""
        self.client.login(username="cap_val", password="password")
        response = self.client.get(reverse('team_detail', kwargs={'slug': self.team.slug}))
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Inline Team verlassen
        self.assertIn('id="leave-team-confirm"', content)
        self.assertIn('toggleLeaveTeamConfirm', content)
        # Inline Kicken für Teammitglieder (player2 ist Mitglied in self.team)
        self.assertIn(f'id="kick-confirm-{self.player2.id}"', content)
        self.assertIn('toggleKickMemberConfirm', content)
        # Keine Browser-Dialoge
        self.assertNotIn('confirm(', content)
        self.assertNotIn('alert(', content)

    def test_team_create_requires_game(self):
        """Teamerstellung erfordert zwingend die Angabe eines gültigen Spiels."""
        self.client.login(username="cap_val", password="password")
        # Ohne game_id
        resp = self.client.post(reverse('team_create'), {'name': 'No Game Team', 'tag': 'NGT'})
        self.assertRedirects(resp, reverse('team_list'))
        self.assertFalse(Team.objects.filter(name='No Game Team').exists())

        # Mit ungültiger game_id
        resp = self.client.post(reverse('team_create'), {'name': 'Bad Game Team', 'tag': 'BGT', 'game_id': '99999'})
        self.assertRedirects(resp, reverse('team_list'))
        self.assertFalse(Team.objects.filter(name='Bad Game Team').exists())

    def test_team_capacity_limits_join_and_apply(self):
        """Volle Teams (z.B. 5 von 5) lehnen Beitritt per Code, Bewerbung und Annahme weiterer Mitglieder ab."""
        new_player = User.objects.create_user(username="extra_player", password="password")
        self.client.login(username="extra_player", password="password")

        # 1. Beitritt per Einladungscode bei vollem Team
        resp = self.client.post(reverse('team_join_by_code'), {'invite_code': self.team.invite_code}, follow=True)
        self.assertContains(resp, "ist bereits voll")
        self.assertFalse(self.team.is_member(new_player))

        # 2. Bewerbung bei vollem Team
        resp = self.client.post(reverse('team_apply', kwargs={'slug': self.team.slug}), follow=True)
        self.assertContains(resp, "ist bereits voll")
        self.assertFalse(TeamMember.objects.filter(team=self.team, user=new_player).exists())

        # 3. Annehmen einer zuvor gestellten Bewerbung wird verhindert, wenn Team voll ist
        pending_membership = TeamMember.objects.create(
            team=self.team,
            user=new_player,
            role=TeamMember.Role.MEMBER,
            status=TeamMember.Status.PENDING
        )
        self.client.login(username="cap_val", password="password")
        resp = self.client.post(
            reverse('team_accept_membership', kwargs={'slug': self.team.slug, 'membership_id': pending_membership.id}),
            follow=True
        )
        self.assertContains(resp, "maximale Mitgliederanzahl")
        pending_membership.refresh_from_db()
        self.assertEqual(pending_membership.status, TeamMember.Status.PENDING)

    def test_tournament_detail_only_shows_matching_game_teams(self):
        """In der Turnieranmeldung werden nur Teams zur Auswahl gestellt, deren Spiel mit dem Turnier übereinstimmt."""
        # Anderes Team für anderes Spiel anlegen
        other_team = Team.objects.create(
            name="CS2 Crew",
            captain=self.captain,
            game=self.other_game,
            event=self.event
        )
        TeamMember.objects.create(team=other_team, user=self.captain, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.client.login(username="cap_val", password="password")
        response = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(response.status_code, 200)

        my_user_teams = response.context['my_user_teams']
        self.assertIn(self.team, my_user_teams)
        self.assertNotIn(other_team, my_user_teams)

    def test_team_detail_and_list_ui_features(self):
        """Prüft das Rendering des hervorgehobenen Teamerstellungs-Modals und der Kaderanzeige im Team-Detail."""
        # 1. team_list zeigt prominente Aktionsleiste und Teamerstellungs-Modal mit Pflichtspiel-Auswahl
        self.client.login(username="cap_val", password="password")
        response = self.client.get(reverse('team_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('id="createTeamModal"', content)
        self.assertIn('name="game_id" required', content)
        self.assertIn('Neues Team gründen', content)
        self.assertIn('Einladungscode eingeben', content)

        # 2. team_detail zeigt Kaderstatus bei vollem Team (5/5)
        response_detail = self.client.get(reverse('team_detail', kwargs={'slug': self.team.slug}))
        self.assertEqual(response_detail.status_code, 200)
        content_detail = response_detail.content.decode('utf-8')
        self.assertIn('Kader vollständig', content_detail)
        self.assertIn('(5/5)', content_detail)

    def test_tournament_preview_restricted_to_admin(self):
        """Vorschau ist für reguläre Teilnehmer verborgen und ausschließlich für Admins sichtbar."""
        # 1. Regulärer Teilnehmer sieht keine Vorschau
        self.client.login(username="cap_val", password="password")
        resp_user = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(resp_user.status_code, 200)
        self.assertIsNone(resp_user.context['preview_data'])
        content_user = resp_user.content.decode('utf-8')
        self.assertNotIn('id="tab-preview"', content_user)
        self.assertNotIn('Admin-Vorschau', content_user)

        # 2. Admin sieht die Vorschau
        admin = User.objects.create_user(username="tourn_admin_val", password="password", is_staff=True)
        self.client.login(username="tourn_admin_val", password="password")
        resp_admin = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(resp_admin.status_code, 200)
        self.assertIsNotNone(resp_admin.context['preview_data'])
        content_admin = resp_admin.content.decode('utf-8')
        self.assertIn('id="tab-preview"', content_admin)
        self.assertIn('Admin-Vorschau', content_admin)

    def test_tournament_preview_double_elimination_rendering(self):
        """Double-Elimination-Vorschau rendert Winner-, Loser-Bracket und Grand Final bei 3 Teams vollständig."""
        # Double Elimination Turnier anlegen
        de_tourn = Tournament.objects.create(
            title="CS2 Double Elimination",
            slug="cs2-de",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=16,
        )

        # 3 Teams für Turnier anmelden
        t1 = self.team
        t2 = Team.objects.create(name="Team Beta", captain=self.player2, game=self.game, event=self.event)
        TeamMember.objects.create(team=t2, user=self.player2, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
        t3 = Team.objects.create(name="Team Gamma", captain=self.player3, game=self.game, event=self.event)
        TeamMember.objects.create(team=t3, user=self.player3, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        TournamentRegistration.objects.create(tournament=de_tourn, team=t1)
        TournamentRegistration.objects.create(tournament=de_tourn, team=t2)
        TournamentRegistration.objects.create(tournament=de_tourn, team=t3)

        # Als Admin aufrufen
        admin = User.objects.create_user(username="de_admin", password="password", is_staff=True)
        self.client.login(username="de_admin", password="password")
        resp = self.client.get(reverse('tournament_detail', kwargs={'slug': de_tourn.slug}))
        self.assertEqual(resp.status_code, 200)

        preview = resp.context['preview_data']
        self.assertIsNotNone(preview)
        self.assertEqual(preview['mode'], 'DOUBLE_ELIMINATION')
        self.assertEqual(preview['total_teams'], 3)
        self.assertEqual(preview['byes'], 1)
        self.assertTrue(len(preview['wb_rounds']) > 0)
        self.assertTrue(len(preview['lb_rounds']) > 0)
        self.assertTrue(len(preview['grand_final']) > 0)

        # HTML prüfen
        content = resp.content.decode('utf-8')
        self.assertIn('Winner Bracket', content)
        self.assertIn('Loser Bracket', content)
        self.assertIn('Grand Final', content)
        self.assertIn('FREILOS', content)
        self.assertIn('Freilose (BYEs):', content)


class TournamentResultReportingAndBracketSeparationTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Lanparty Spring 2026",
            slug="lanparty-spring-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Counter-Strike 2", mode="5v5", team_size=5)

        self.admin_user = User.objects.create_user(username="tourn_admin", password="password", is_staff=True)
        self.u1 = User.objects.create_user(username="player_t1", password="password")
        self.u2 = User.objects.create_user(username="player_t2", password="password")
        self.u3 = User.objects.create_user(username="player_t3", password="password")
        self.unrelated = User.objects.create_user(username="unrelated_user", password="password")

        # Event Check-ins
        for u in [self.admin_user, self.u1, self.u2, self.u3, self.unrelated]:
            EventRegistration.objects.create(
                user=u, event=self.event,
                payment_status=EventRegistration.PaymentStatus.PAID,
                is_checked_in=True
            )

        self.team1 = Team.objects.create(name="Team Alpha", captain=self.u1, game=self.game, event=self.event)
        TeamMember.objects.create(team=self.team1, user=self.u1, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.team2 = Team.objects.create(name="Team Bravo", captain=self.u2, game=self.game, event=self.event)
        TeamMember.objects.create(team=self.team2, user=self.u2, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.team3 = Team.objects.create(name="Team Charlie", captain=self.u3, game=self.game, event=self.event)
        TeamMember.objects.create(team=self.team3, user=self.u3, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        self.tournament = Tournament.objects.create(
            title="CS2 Champions Cup",
            slug="cs2-champions-cup",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            registration_start=timezone.now() - timedelta(days=1),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.REGISTRATION_OPEN,
            max_teams=8,
            tournament_admin=self.admin_user,
        )

        TournamentRegistration.objects.create(tournament=self.tournament, team=self.team1)
        TournamentRegistration.objects.create(tournament=self.tournament, team=self.team2)
        TournamentRegistration.objects.create(tournament=self.tournament, team=self.team3)

    def test_participant_can_report_own_defeat(self):
        """Verlierer-Team kann das Match-Ergebnis selbst eintragen, wenn es den Gegner als Sieger bestätigt."""
        from tournaments.services import TournamentBracketService
        TournamentBracketService.generate_bracket(self.tournament.id, actor=self.admin_user)

        # Erstes spielbares Match holen (team1 vs team2)
        match = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).filter(team1__isnull=False, team2__isnull=False).first()
        self.assertIsNotNone(match)

        # Kapitän von match.team1 meldet Niederlage (match.team2 gewinnt)
        user = match.team1.captain
        self.client.login(username=user.username, password="password")
        url = reverse('match_update_score', kwargs={'match_id': match.id})
        resp = self.client.post(url, {
            'score_team1': 0,
            'score_team2': 1,
            'winner_id': match.team2.id,
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['winner'], match.team2.name)

        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(match.winner, match.team2)
        self.assertEqual(match.loser, match.team1)
        self.assertIn(user.username, match.decision_reason)

    def test_participant_cannot_declare_themselves_winner(self):
        """Teilnehmer darf sich nicht selbst als Sieger eintragen (Fairplay-Schutz)."""
        from tournaments.services import TournamentBracketService
        TournamentBracketService.generate_bracket(self.tournament.id, actor=self.admin_user)

        match = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).filter(team1__isnull=False, team2__isnull=False).first()

        # Kapitän von match.team1 versucht, match.team1 als Sieger einzutragen
        user = match.team1.captain
        self.client.login(username=user.username, password="password")
        url = reverse('match_update_score', kwargs={'match_id': match.id})
        resp = self.client.post(url, {
            'score_team1': 2,
            'score_team2': 0,
            'winner_id': match.team1.id,
        })
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data['success'])
        self.assertIn("nur die eigene Niederlage bestätigen", data['error'])

        match.refresh_from_db()
        self.assertNotEqual(match.status, TournamentMatch.Status.COMPLETED)

    def test_unrelated_user_forbidden(self):
        """Ein unbeteiligter Benutzer ohne Admin-Rechte erhält 403 Forbidden."""
        from tournaments.services import TournamentBracketService
        TournamentBracketService.generate_bracket(self.tournament.id, actor=self.admin_user)

        match = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).filter(team1__isnull=False, team2__isnull=False).first()

        self.client.login(username="unrelated_user", password="password")
        url = reverse('match_update_score', kwargs={'match_id': match.id})
        resp = self.client.post(url, {
            'score_team1': 0,
            'score_team2': 1,
            'winner_id': match.team2.id,
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.json()
        self.assertFalse(data['success'])

    def test_participant_cannot_edit_completed_match(self):
        """Teilnehmer dürfen bereits gewertete Matches nicht nachträglich überschreiben."""
        from tournaments.services import TournamentBracketService
        TournamentBracketService.generate_bracket(self.tournament.id, actor=self.admin_user)

        match = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).filter(team1__isnull=False, team2__isnull=False).first()

        # Admin trägt Ergebnis ein
        self.client.login(username="tourn_admin", password="password")
        url = reverse('match_update_score', kwargs={'match_id': match.id})
        self.client.post(url, {
            'score_team1': 1,
            'score_team2': 0,
            'winner_id': match.team1.id,
        })
        match.refresh_from_db()
        self.assertEqual(match.status, TournamentMatch.Status.COMPLETED)

        # Teilnehmer versucht zu bearbeiten -> 403
        user = match.team2.captain
        self.client.login(username=user.username, password="password")
        resp = self.client.post(url, {
            'score_team1': 0,
            'score_team2': 1,
            'winner_id': match.team1.id,
        })
        self.assertEqual(resp.status_code, 403)

    def test_double_elimination_separation_status_and_podium(self):
        """Turnier schließt nach Grand Final ab, schaltet auf FINISHED und zeigt Podium & getrennte Brackets."""
        from tournaments.services import TournamentBracketService, TournamentMatchService
        TournamentBracketService.generate_bracket(self.tournament.id, actor=self.admin_user)

        # Alle Matches abarbeiten
        # 1. WB R1 (Team 2 vs Team 3)
        wb_r1 = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).first()
        TournamentMatchService.update_match_score(
            match_id=wb_r1.id, score1=16, score2=5,
            winner_id=wb_r1.team1.id, actor=self.admin_user
        )

        # 2. WB Finale (Team 1 vs Team 2)
        wb_final = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        ).first()
        TournamentMatchService.update_match_score(
            match_id=wb_final.id, score1=16, score2=8,
            winner_id=wb_final.team1.id, actor=self.admin_user
        )

        # 3. LB Finale (Team 3 vs Team 2)
        lb_final = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.LOSERS,
            status=TournamentMatch.Status.READY
        ).first()
        self.assertIsNotNone(lb_final)
        TournamentMatchService.update_match_score(
            match_id=lb_final.id, score1=10, score2=16,
            winner_id=lb_final.team2.id, actor=self.admin_user
        )

        # 4. Grand Final (Team 1 vs Team 2)
        gf_match = self.tournament.matches.filter(
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL,
            status=TournamentMatch.Status.READY
        ).first()
        self.assertIsNotNone(gf_match)
        TournamentMatchService.update_match_score(
            match_id=gf_match.id, score1=16, score2=12,
            winner_id=gf_match.team1.id, actor=self.admin_user
        )

        # Turnier muss automatisch FINISHED sein
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.status, Tournament.Status.FINISHED)

        # Detailseite aufrufen
        resp = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(resp.status_code, 200)

        # Brackets im Kontext getrennt
        self.assertTrue(len(resp.context['wb_matches']) > 0)
        self.assertTrue(len(resp.context['lb_matches']) > 0)
        self.assertTrue(len(resp.context['grand_final_matches']) > 0)

        # Podium ermittelt
        podium = resp.context['podium']
        self.assertEqual(podium['first'], gf_match.team1)
        self.assertEqual(podium['second'], gf_match.team2)
        self.assertIsNotNone(podium['third'])

        # HTML-Überprüfung
        html = resp.content.decode('utf-8')
        self.assertIn("🏁 Turnier beendet", html)
        self.assertNotIn("⚔️ Turnier läuft", html)
        self.assertIn("Siegerehrung &amp; Endstand", html)
        self.assertIn("Turniersieger", html)
        self.assertIn("Winner Bracket (Hauptfeld)", html)
        self.assertIn("Loser Bracket (Hoffnungsrunde)", html)
        self.assertIn("Grand Final (Entscheidungsspiel)", html)


class TournamentTranslationMaintenanceTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

        self.event = Event.objects.create(
            title="LAN Party 2026",
            slug="lan-party-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Rocket League", team_size=3)
        self.user = User.objects.create_user(username="gamer1", email="gamer1@example.com", password="password123")
        self.tournament = Tournament.objects.create(
            title="RL Cup",
            event=self.event,
            game=self.game,
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(days=1),
            registration_end=timezone.now() + timedelta(days=1),
        )

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()

    def test_tournament_mode_display_dynamic_override(self):
        from django.core.cache import cache
        from configuration.models import SystemTranslation

        # 1. Default display
        self.assertEqual(self.tournament.get_mode_display(), "Double Elimination (Winner + Loser Bracket)")

        # 2. Detail view shows default
        resp = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Double Elimination (Winner + Loser Bracket)", resp.content.decode('utf-8'))

        # 3. Override mode translation via SystemTranslation
        SystemTranslation.objects.update_or_create(
            key="tournament_mode_double_elimination",
            defaults={'text': "Doppel-KO (Haupt- & Hoffnungsrunde)"}
        )
        cache.clear()

        # 4. Model get_mode_display() returns custom text
        self.assertEqual(self.tournament.get_mode_display(), "Doppel-KO (Haupt- & Hoffnungsrunde)")

        # 5. Detail view shows customized mode text
        resp2 = self.client.get(reverse('tournament_detail', kwargs={'slug': self.tournament.slug}))
        self.assertIn("Doppel-KO (Haupt- &amp; Hoffnungsrunde)", resp2.content.decode('utf-8'))

    def test_tournament_admin_choices_dynamic(self):
        from django.core.cache import cache
        from configuration.models import SystemTranslation
        from django.contrib.admin.sites import AdminSite
        from tournaments.admin import TournamentAdmin
        from unittest.mock import MagicMock

        SystemTranslation.objects.update_or_create(
            key="tournament_mode_single_elimination",
            defaults={'text': "Einfaches KO-System (Klassisch)"}
        )
        cache.clear()

        site = AdminSite()
        admin_obj = TournamentAdmin(Tournament, site)
        mode_field = Tournament._meta.get_field('mode')
        req = MagicMock()
        form_field = admin_obj.formfield_for_choice_field(mode_field, req)
        choices_dict = dict(form_field.choices)

        self.assertEqual(choices_dict[Tournament.Mode.SINGLE_ELIMINATION], "Einfaches KO-System (Klassisch)")

    def test_tournament_match_and_team_translations(self):
        from django.core.cache import cache
        from configuration.models import SystemTranslation

        team = Team.objects.create(name="Team A", captain=self.user, game=self.game)
        member = TeamMember.objects.create(
            team=team, user=self.user, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED
        )
        self.assertEqual(member.get_role_display(), "👑 Kapitän")

        match = TournamentMatch.objects.create(
            tournament=self.tournament,
            match_number=1,
            round_number=1,
            bracket_type=TournamentMatch.BracketType.WINNERS,
            status=TournamentMatch.Status.READY
        )
        self.assertEqual(match.get_bracket_type_display(), "Winner Bracket")
        self.assertEqual(match.get_status_display(), "Bereit")

        # Customization
        SystemTranslation.objects.update_or_create(
            key="tournament_bracket_winners",
            defaults={'text': "Gewinner-Feld"}
        )
        cache.clear()
        self.assertEqual(match.get_bracket_type_display(), "Gewinner-Feld")

    def test_team_create_flash_message_translated(self):
        from django.core.cache import cache
        from configuration.models import SystemTranslation
        from django.contrib.messages import get_messages

        SystemTranslation.objects.update_or_create(
            key="msg_team_name_required",
            defaults={'text': "Fehler: Bitte einen Teamnamen eingeben!"}
        )
        cache.clear()

        self.client.force_login(self.user)
        resp = self.client.post(reverse('team_create'), {'name': '', 'game_id': self.game.id})
        self.assertEqual(resp.status_code, 302)

        messages = list(get_messages(resp.wsgi_request))
        self.assertTrue(any("Fehler: Bitte einen Teamnamen eingeben!" in str(m) for m in messages))


class TournamentResultProtectionTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Protection LAN",
            slug="protection-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Game 1", mode="1v1", team_size=1)
        self.admin_user = User.objects.create_superuser("admin_prot", "admin_prot@example.com", "pass")
        self.u1 = User.objects.create_user("u1", "u1@example.com", "pass")
        self.u2 = User.objects.create_user("u2", "u2@example.com", "pass")
        self.u3 = User.objects.create_user("u3", "u3@example.com", "pass")
        self.u4 = User.objects.create_user("u4", "u4@example.com", "pass")
        self.t1 = Team.objects.create(name="T1", captain=self.u1, game=self.game)
        self.t2 = Team.objects.create(name="T2", captain=self.u2, game=self.game)
        self.t3 = Team.objects.create(name="T3", captain=self.u3, game=self.game)
        self.t4 = Team.objects.create(name="T4", captain=self.u4, game=self.game)

    def test_score_change_rejected_when_tournament_finished(self):
        """Ergebnisänderungen in bereits abgeschlossenen Turnieren werden abgelehnt."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="Finished Cup",
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.FINISHED,
        )
        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FINAL,
            team1=self.t1,
            team2=self.t2,
            score_team1=16,
            score_team2=10,
            winner=self.t1,
            loser=self.t2,
            status=TournamentMatch.Status.COMPLETED,
        )
        with self.assertRaises(MatchAlreadyCompletedError):
            TournamentMatchService.update_match_score(
                match_id=match.id,
                score1=10,
                score2=16,
                winner_id=self.t2.id,
            )

    def test_group_stage_score_change_rejected_if_playoffs_active(self):
        """Änderung eines Gruppenspiels ablehnen, wenn Finalspiele bereits begonnen oder abgeschlossen wurden."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="Group Cup",
            mode=Tournament.Mode.GROUP_STAGE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        group_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GROUP,
            group_name="Gruppe A",
            team1=self.t1,
            team2=self.t2,
            score_team1=16,
            score_team2=10,
            winner=self.t1,
            status=TournamentMatch.Status.COMPLETED,
        )
        # Playoff match ist bereits IN_PROGRESS
        playoff_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=2,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FINAL,
            team1=self.t1,
            team2=self.t3,
            status=TournamentMatch.Status.IN_PROGRESS,
        )
        with self.assertRaises(MatchAlreadyCompletedError):
            TournamentMatchService.update_match_score(
                match_id=group_match.id,
                score1=5,
                score2=16,
                winner_id=self.t2.id,
            )

    def test_grand_final_score_change_rejected_if_reset_active(self):
        """Änderung des Grand Finals ablehnen, wenn das Grand Final Reset Match bereits läuft oder abgeschlossen ist."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="DE Grand Final Cup",
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        gf_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=3,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL,
            team1=self.t1,
            team2=self.t2,
            score_team1=10,
            score_team2=16,
            winner=self.t2,
            loser=self.t1,
            status=TournamentMatch.Status.COMPLETED,
        )
        reset_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=4,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GRAND_FINAL_RESET,
            team1=self.t1,
            team2=self.t2,
            status=TournamentMatch.Status.IN_PROGRESS,
        )
        with self.assertRaises(MatchAlreadyCompletedError):
            TournamentMatchService.update_match_score(
                match_id=gf_match.id,
                score1=16,
                score2=10,
                winner_id=self.t1.id,
            )

    def test_check_and_advance_group_stage_preserves_active_playoffs(self):
        """check_and_advance_group_stage überschreibt keine Finalspiele, die bereits laufen oder fertig sind."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="Group Preservation Cup",
            mode=Tournament.Mode.GROUP_STAGE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        TournamentRegistration.objects.create(tournament=tournament, team=self.t1, group_name="Gruppe A")
        TournamentRegistration.objects.create(tournament=tournament, team=self.t2, group_name="Gruppe A")
        TournamentRegistration.objects.create(tournament=tournament, team=self.t3, group_name="Gruppe B")
        TournamentRegistration.objects.create(tournament=tournament, team=self.t4, group_name="Gruppe B")

        # Gruppe A & B Matches
        TournamentMatch.objects.create(
            tournament=tournament, round_number=1, match_number=1,
            bracket_type=TournamentMatch.BracketType.GROUP, group_name="Gruppe A",
            team1=self.t1, team2=self.t2, score_team1=16, score_team2=5, winner=self.t1,
            status=TournamentMatch.Status.COMPLETED,
        )
        TournamentMatch.objects.create(
            tournament=tournament, round_number=1, match_number=2,
            bracket_type=TournamentMatch.BracketType.GROUP, group_name="Gruppe B",
            team1=self.t3, team2=self.t4, score_team1=16, score_team2=5, winner=self.t3,
            status=TournamentMatch.Status.COMPLETED,
        )
        # Finale existiert und ist COMPLETED
        final_match = TournamentMatch.objects.create(
            tournament=tournament, round_number=2, match_number=1,
            bracket_type=TournamentMatch.BracketType.FINAL,
            team1=self.t1, team2=self.t3, score_team1=16, score_team2=12, winner=self.t1,
            status=TournamentMatch.Status.COMPLETED,
        )
        advanced = GroupStageStandingService.check_and_advance_group_stage(tournament)
        self.assertFalse(advanced)
        final_match.refresh_from_db()
        self.assertEqual(final_match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(final_match.winner, self.t1)


class ForfeitedTeamAdvancementTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Forfeit LAN",
            slug="forfeit-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Game F", mode="1v1", team_size=1)
        self.u1 = User.objects.create_user("fu1", "fu1@example.com", "pass")
        self.u2 = User.objects.create_user("fu2", "fu2@example.com", "pass")
        self.u3 = User.objects.create_user("fu3", "fu3@example.com", "pass")
        self.t1 = Team.objects.create(name="T1", captain=self.u1, game=self.game)
        self.t2 = Team.objects.create(name="T2", captain=self.u2, game=self.game)
        self.t3 = Team.objects.create(name="T3", captain=self.u3, game=self.game)

    def test_forfeited_team_does_not_advance_to_loser_bracket_and_opponent_gets_bye(self):
        """Ein aufgegebenes Team wird nicht im Loser Bracket eingesetzt; der Gegner erhält ein Freilos (BYE)."""
        from tournaments.services import forfeit_team_in_active_tournaments
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="DE Forfeit Cup",
            mode=Tournament.Mode.DOUBLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        reg1 = TournamentRegistration.objects.create(tournament=tournament, team=self.t1)
        reg2 = TournamentRegistration.objects.create(tournament=tournament, team=self.t2)
        reg3 = TournamentRegistration.objects.create(tournament=tournament, team=self.t3)

        # Match in WB: T1 vs T2
        # Folgematch für Loser: lb_match
        lb_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.LOSERS,
            team1=self.t3,
            team2=None,
            status=TournamentMatch.Status.PENDING,
        )
        wb_match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.WINNERS,
            team1=self.t1,
            team2=self.t2,
            next_match_loser=lb_match,
            next_match_loser_slot=2,
            status=TournamentMatch.Status.READY,
        )

        # T2 gibt auf
        forfeit_team_in_active_tournaments(self.t2, reason="Aufgabe Test")

        # Turnieranmeldung von T2 muss is_forfeited=True haben
        reg2.refresh_from_db()
        self.assertTrue(reg2.is_forfeited)

        # wb_match muss durch den Walkover abgeschlossen sein mit Sieger T1
        wb_match.refresh_from_db()
        self.assertEqual(wb_match.status, TournamentMatch.Status.COMPLETED)
        self.assertEqual(wb_match.winner, self.t1)
        self.assertEqual(wb_match.loser, self.t2)

        # lb_match darf T2 NICHT als team2 erhalten, sondern T3 muss sofort ein Freilos (BYE) bekommen!
        lb_match.refresh_from_db()
        self.assertNotEqual(lb_match.team2, self.t2)
        self.assertTrue(lb_match.is_bye)
        self.assertEqual(lb_match.winner, self.t3)
        self.assertEqual(lb_match.status, TournamentMatch.Status.COMPLETED)


class LeagueAndGroupStageDrawTests(TestCase):
    def setUp(self):
        self.event = Event.objects.create(
            title="Draw LAN",
            slug="draw-lan",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=2),
        )
        self.game = Game.objects.create(name="Draw Game", mode="1v1", team_size=1)
        self.u1 = User.objects.create_user("du1", "du1@example.com", "pass")
        self.u2 = User.objects.create_user("du2", "du2@example.com", "pass")
        self.t1 = Team.objects.create(name="D1", captain=self.u1, game=self.game)
        self.t2 = Team.objects.create(name="D2", captain=self.u2, game=self.game)

    def test_draw_allowed_in_league(self):
        """Unentschieden in Ligaturnieren ist erlaubt und führt zu winner=None, loser=None."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="League Draw",
            mode=Tournament.Mode.LEAGUE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GROUP,
            team1=self.t1,
            team2=self.t2,
            status=TournamentMatch.Status.READY,
        )
        m, winner = TournamentMatchService.update_match_score(
            match_id=match.id,
            score1=10,
            score2=10,
        )
        self.assertIsNone(winner)
        self.assertIsNone(m.winner)
        self.assertIsNone(m.loser)
        self.assertEqual(m.status, TournamentMatch.Status.COMPLETED)

        # Ligatabelle prüfen
        TournamentRegistration.objects.create(tournament=tournament, team=self.t1)
        TournamentRegistration.objects.create(tournament=tournament, team=self.t2)
        standings = LeagueStandingService.calculate_league_standings(tournament)
        self.assertEqual(len(standings), 2)
        self.assertEqual(standings[0]['points'], 1)
        self.assertEqual(standings[1]['points'], 1)
        self.assertEqual(standings[0]['drawn'], 1)
        self.assertEqual(standings[1]['drawn'], 1)

    def test_draw_allowed_in_group_stage(self):
        """Unentschieden in Gruppenphase ist erlaubt."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="Group Draw",
            mode=Tournament.Mode.GROUP_STAGE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GROUP,
            group_name="Gruppe A",
            team1=self.t1,
            team2=self.t2,
            status=TournamentMatch.Status.READY,
        )
        m, winner = TournamentMatchService.update_match_score(
            match_id=match.id,
            score1=5,
            score2=5,
        )
        self.assertIsNone(winner)
        self.assertIsNone(m.winner)
        self.assertIsNone(m.loser)
        self.assertEqual(m.status, TournamentMatch.Status.COMPLETED)

    def test_draw_rejected_in_ko(self):
        """Unentschieden in K.O.-Matches ohne Siegerauswahl wird abgelehnt."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="KO Cup",
            mode=Tournament.Mode.SINGLE_ELIMINATION,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.FINAL,
            team1=self.t1,
            team2=self.t2,
            status=TournamentMatch.Status.READY,
        )
        with self.assertRaises(InvalidWinnerError):
            TournamentMatchService.update_match_score(
                match_id=match.id,
                score1=10,
                score2=10,
            )

    def test_match_update_score_view_draw(self):
        """View gibt bei Unentschieden draw: True und 200 zurück."""
        tournament = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="View Draw Cup",
            mode=Tournament.Mode.LEAGUE,
            registration_start=timezone.now(),
            registration_end=timezone.now() + timedelta(days=1),
            status=Tournament.Status.IN_PROGRESS,
        )
        match = TournamentMatch.objects.create(
            tournament=tournament,
            round_number=1,
            match_number=1,
            bracket_type=TournamentMatch.BracketType.GROUP,
            team1=self.t1,
            team2=self.t2,
            status=TournamentMatch.Status.READY,
        )
        admin = User.objects.create_superuser("admin_draw", "admin_draw@example.com", "pass")
        self.client.force_login(admin)
        resp = self.client.post(
            reverse('match_update_score', kwargs={'match_id': match.id}),
            {'score1': 5, 'score2': 5},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
class TournamentQueryPerformanceTests(TestCase):
    """
    Performance- und Regressions-Tests zur Sicherstellung optimierter Query-Budgets (keine N+1-Abfragen).
    """

    def setUp(self):
        self.event = Event.objects.create(
            title="LAN Event 2026",
            slug="lan-2026",
            is_active=True,
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=3),
        )
        self.game = Game.objects.create(name="Game 1", mode="1v1", team_size=1)
        self.user = User.objects.create_user(username="testuser", email="user@example.com", password="pw")

    def test_tournament_list_constant_queries_regardless_of_tournament_count(self):
        """
        Prüft, dass die Turnierliste keine separaten COUNT-Queries je Turnier ausführt (N+1-Vermeidung).
        9 zusätzliche Turniere dürfen die Anzahl der Datenbank-Abfragen um 0 erhöhen (O(1)).
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Baseline mit 1 Turnier
        t0 = Tournament.objects.create(
            event=self.event,
            game=self.game,
            title="Tournament 0",
            status=Tournament.Status.REGISTRATION_OPEN,
            registration_start=timezone.now() - timedelta(days=1),
            registration_end=timezone.now() + timedelta(days=1),
        )
        u0 = User.objects.create_user(username="u_0", email="u_0@test.de", password="pw")
        team0 = Team.objects.create(name="T_0", captain=u0, game=self.game, event=self.event)
        TournamentRegistration.objects.create(tournament=t0, team=team0)

        # Einmal aufrufen zur Cache-Aufwärmung
        self.client.get(reverse('tournament_list'))

        with CaptureQueriesContext(connection) as ctx1:
            resp1 = self.client.get(reverse('tournament_list'))
            self.assertEqual(resp1.status_code, 200)
        q1 = len(ctx1.captured_queries)

        # 9 weitere Turniere anlegen (insgesamt 10 Turniere mit Registrierungen)
        for i in range(1, 10):
            t = Tournament.objects.create(
                event=self.event,
                game=self.game,
                title=f"Tournament {i}",
                status=Tournament.Status.REGISTRATION_OPEN,
                registration_start=timezone.now() - timedelta(days=1),
                registration_end=timezone.now() + timedelta(days=1),
            )
            for j in range(2):
                u = User.objects.create_user(username=f"u_{i}_{j}", email=f"u_{i}_{j}@test.de", password="pw")
                team = Team.objects.create(name=f"T_{i}_{j}", captain=u, game=self.game, event=self.event)
                TournamentRegistration.objects.create(tournament=t, team=team)

        with CaptureQueriesContext(connection) as ctx10:
            resp10 = self.client.get(reverse('tournament_list'))
            self.assertEqual(resp10.status_code, 200)
            self.assertContains(resp10, "Tournament 0")
            self.assertContains(resp10, "Tournament 9")
        q10 = len(ctx10.captured_queries)

        # 9 zusätzliche Turniere dürfen die Query-Anzahl NICHT erhöhen (N+1-Freiheit)
        self.assertEqual(q1, q10)
        self.assertLessEqual(q10, 5)

    def test_team_list_constant_queries_regardless_of_team_count(self):
        """
        Prüft, dass die Teamliste (aktiv & mein Team) keine N+1-Queries für die Mitgliederanzahl ausführt.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.user)

        # 1 Team anlegen
        c0 = User.objects.create_user(username="capt_0", email="capt_0@test.de", password="pw")
        team0 = Team.objects.create(name="Team 0", captain=c0, game=self.game, event=self.event)
        TeamMember.objects.create(team=team0, user=c0, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)

        # Cache-Aufwärmung
        self.client.get(reverse('team_list'))

        with CaptureQueriesContext(connection) as ctx1:
            resp1 = self.client.get(reverse('team_list'))
            self.assertEqual(resp1.status_code, 200)
        q1 = len(ctx1.captured_queries)

        # 9 weitere Teams anlegen (insgesamt 10 Teams mit mehreren Mitgliedern)
        for i in range(1, 10):
            captain = User.objects.create_user(username=f"capt_{i}", email=f"capt_{i}@test.de", password="pw")
            team = Team.objects.create(name=f"Team {i}", captain=captain, game=self.game, event=self.event)
            TeamMember.objects.create(team=team, user=captain, role=TeamMember.Role.CAPTAIN, status=TeamMember.Status.ACCEPTED)
            m = User.objects.create_user(username=f"mem_{i}", email=f"mem_{i}@test.de", password="pw")
            TeamMember.objects.create(team=team, user=m, role=TeamMember.Role.MEMBER, status=TeamMember.Status.ACCEPTED)

        with CaptureQueriesContext(connection) as ctx10:
            resp10 = self.client.get(reverse('team_list'))
            self.assertEqual(resp10.status_code, 200)
            self.assertContains(resp10, "Team 0")
            self.assertContains(resp10, "Team 9")
        q10 = len(ctx10.captured_queries)

        # 9 zusätzliche Teams dürfen die Query-Anzahl nicht erhöhen (keine N+1 member count queries)
        self.assertLessEqual(q10, q1)
        self.assertLessEqual(q10, 15)











