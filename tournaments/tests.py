from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from users.models import User
from events.models import Event, EventRegistration
from tournaments.models import Game, Tournament, Team, TeamMember, TournamentRegistration, TournamentMatch
from tournaments.services import (
    advance_match_winner, check_user_event_checkin, generate_bracket, get_or_create_solo_team
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


