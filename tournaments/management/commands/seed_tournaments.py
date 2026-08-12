from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from events.models import Event, EventRegistration
from users.models import User
from tournaments.models import Game, Tournament, Team, TeamMember, TournamentRegistration
from tournaments.services import generate_bracket


class Command(BaseCommand):
    help = 'Erstellt Demo-Spiele, Demoturniere und Beispieldaten für das Turnier-Modul.'

    def handle(self, *args, **options):
        active_event = Event.objects.filter(is_active=True).first()
        if not active_event:
            active_event = Event.objects.create(
                title="Entails-NG Summer LAN 2026",
                slug="summer-lan-2026",
                is_active=True,
                start_date=timezone.now(),
                end_date=timezone.now() + timedelta(days=3),
                status=Event.Status.RUNNING
            )

        # 1. Spiele anlegen
        cs2, _ = Game.objects.get_or_create(
            name="Counter-Strike 2",
            defaults={
                'mode': '5v5 Bomb Defusal',
                'team_size': 5,
                'rules': 'MR12, Overtime Maxrounds 6, Competitive Map Pool.',
                'additional_info': 'Server-IPs werden 15 Min vor Matchbeginn bereitgestellt.'
            }
        )

        rl, _ = Game.objects.get_or_create(
            name="Rocket League",
            defaults={
                'mode': '3v3 Soccar',
                'team_size': 3,
                'rules': 'Standard 3v3 Arena, Best of 3/5.',
                'additional_info': 'Crossplay aktiviert.'
            }
        )

        sc2, _ = Game.objects.get_or_create(
            name="StarCraft II",
            defaults={
                'mode': '1v1 Melee',
                'team_size': 1,
                'rules': '1v1 Ladder Maps, Best of 3.',
                'additional_info': 'Veto-Phase vor jedem Match.'
            }
        )

        hldm, _ = Game.objects.get_or_create(
            name="Half-Life Deathmatch",
            defaults={
                'mode': 'Free For All',
                'team_size': 1,
                'rules': '15 Minuten Time-Limit, wer am Schluss die meisten Kills hat gewinnt.',
                'additional_info': 'Map: crossfire.'
            }
        )

        # 2. Demo User & Check-in einrichten
        test_users = []
        for i in range(1, 9):
            u, _ = User.objects.get_or_create(
                username=f"gamer_{i}",
                defaults={'email': f"gamer_{i}@example.com", 'first_name': f"Gamer{i}"}
            )
            u.set_password("password123")
            u.save()
            test_users.append(u)

            # Check-in für Event aktivieren damit sie sich anmelden können
            reg, _ = EventRegistration.objects.get_or_create(user=u, event=active_event)
            reg.is_checked_in = True
            reg.payment_status = EventRegistration.PaymentStatus.PAID
            reg.save()

        # 3. Turniere anlegen
        t1, _ = Tournament.objects.get_or_create(
            title="CS2 Main Championship",
            event=active_event,
            defaults={
                'game': cs2,
                'mode': Tournament.Mode.SINGLE_ELIMINATION,
                'max_teams': 8,
                'registration_start': timezone.now() - timedelta(days=1),
                'registration_end': timezone.now() + timedelta(days=2),
                'status': Tournament.Status.REGISTRATION_OPEN,
                'description': 'Das CS2 Hauptturnier mit Pokal & Sachpreisen!'
            }
        )

        t2, _ = Tournament.objects.get_or_create(
            title="StarCraft II 1v1 Cup",
            event=active_event,
            defaults={
                'game': sc2,
                'mode': Tournament.Mode.DOUBLE_ELIMINATION,
                'max_teams': 16,
                'registration_start': timezone.now() - timedelta(days=1),
                'registration_end': timezone.now() + timedelta(days=2),
                'status': Tournament.Status.REGISTRATION_OPEN,
                'description': '1v1 Double Elimination für Strategie-Experten.'
            }
        )

        # 4. Demo Teams & Anmeldungen anlegen
        team_alpha, _ = Team.objects.get_or_create(
            name="Alpha Gamers",
            defaults={'tag': 'ALPHA', 'captain': test_users[0], 'game': cs2}
        )
        TeamMember.objects.get_or_create(team=team_alpha, user=test_users[0], defaults={'role': TeamMember.Role.CAPTAIN})
        TeamMember.objects.get_or_create(team=team_alpha, user=test_users[1])

        team_bravo, _ = Team.objects.get_or_create(
            name="Team Bravo",
            defaults={'tag': 'BRV', 'captain': test_users[2], 'game': cs2}
        )
        TeamMember.objects.get_or_create(team=team_bravo, user=test_users[2], defaults={'role': TeamMember.Role.CAPTAIN})
        TeamMember.objects.get_or_create(team=team_bravo, user=test_users[3])

        team_charlie, _ = Team.objects.get_or_create(
            name="Charlie Squad",
            defaults={'tag': 'CHS', 'captain': test_users[4], 'game': cs2}
        )
        TeamMember.objects.get_or_create(team=team_charlie, user=test_users[4], defaults={'role': TeamMember.Role.CAPTAIN})
        TeamMember.objects.get_or_create(team=team_charlie, user=test_users[5])

        # Anmeldungen für CS2 Turnier
        TournamentRegistration.objects.get_or_create(tournament=t1, team=team_alpha)
        TournamentRegistration.objects.get_or_create(tournament=t1, team=team_bravo)
        TournamentRegistration.objects.get_or_create(tournament=t1, team=team_charlie)

        self.stdout.write(self.style.SUCCESS("✅ Turnier-Demodaten erfolgreich angelegt!"))
