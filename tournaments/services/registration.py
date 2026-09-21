import logging
from django.db import transaction
from django.utils import timezone

from events.models import EventRegistration
from tournaments.exceptions import (
    TournamentAlreadyRegisteredError,
    TournamentError,
    TournamentFullError,
    TournamentNotCheckedInError,
    TournamentNotOpenError,
    TournamentRegistrationError,
)
from tournaments.models import (
    Team,
    TeamMember,
    Tournament,
    TournamentRegistration,
)

logger = logging.getLogger(__name__)


def check_user_event_checkin(user, event):
    """
    Prüft, ob der angegebene Benutzer für das aktive Event eingecheckt ist.
    """
    if not user or not user.is_authenticated or not event:
        return False
    return EventRegistration.objects.filter(
        user=user,
        event=event,
        is_checked_in=True
    ).exists()


def archive_teams_for_event(event):
    """
    Archiviert alle Teams, die der angegebenen Veranstaltung zugeordnet sind
    oder an Turnieren dieser Veranstaltung teilgenommen haben.
    """
    if not event:
        return 0
    direct_teams = Team.objects.filter(event=event, is_archived=False)
    tournament_teams = Team.objects.filter(
        tournament_registrations__tournament__event=event,
        is_archived=False
    )
    combined_ids = set(direct_teams.values_list('id', flat=True)) | set(tournament_teams.values_list('id', flat=True))
    count = Team.objects.filter(id__in=combined_ids).update(is_archived=True, event=event)
    return count


def get_or_create_solo_team(user, game):
    """
    Erstellt oder holt ein 1v1 Solo-Team für den angegebenen Benutzer und das angegebene Spiel.
    """
    team_name = f"{user.username} (Solo)"
    team = Team.objects.filter(captain=user, game=game, is_solo=True).first()
    if not team:
        team = Team.objects.create(
            name=team_name,
            game=game,
            captain=user,
            is_solo=True,
        )
        TeamMember.objects.get_or_create(
            team=team,
            user=user,
            defaults={
                'role': TeamMember.Role.CAPTAIN,
                'status': TeamMember.Status.ACCEPTED,
            }
        )
    return team


class TournamentRegistrationService:
    @staticmethod
    def register_team(tournament_id, user, team_id=None, actor=None):
        """
        Meldet ein Team oder einen Solo-Spieler transaktionssicher für ein Turnier an.
        Prüft Zeitfenster, Vor-Ort Check-in, Kapazitätslimits und Team-Berechtigungen.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().select_related('game', 'event').get(pk=tournament_id)

            # 1. Privilegien-Check (Staff / Superuser / Turnier-Admin)
            is_privileged = tournament.is_managed_by(actor)

            # 2. Vor-Ort Check-in des anmeldenden Benutzers prüfen
            if not is_privileged and not check_user_event_checkin(user, tournament.event):
                raise TournamentNotCheckedInError(
                    "Nur vor Ort eingecheckte Gäste können sich für Turniere anmelden! Bitte checke zuerst am Einlass ein."
                )

            # 3. Team bestimmen / Solo-Team erzeugen
            if tournament.game.team_size == 1:
                team = get_or_create_solo_team(user, tournament.game)
            else:
                if not team_id:
                    raise TournamentRegistrationError("Bitte wähle ein Team für die Anmeldung aus.")
                team = Team.objects.filter(id=team_id).first()
                if not team:
                    raise TournamentRegistrationError("Das ausgewählte Team wurde nicht gefunden.")

                # 3.1 Archivierungsprüfung
                if team.is_archived:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' ist archiviert und kann nicht angemeldet werden. Bitte reaktiviere das Team zuerst im Teammanager."
                    )

                # 3.2 Event-Zugehörigkeit prüfen
                if team.event and tournament.event and team.event != tournament.event:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' gehört zur Veranstaltung '{team.event.title}' und kann nicht für '{tournament.event.title}' antreten."
                    )
                elif not team.event and tournament.event:
                    team.event = tournament.event
                    team.save(update_fields=['event'])

                # 3.3 Spiel-Passung prüfen
                if not team.game:
                    raise TournamentRegistrationError(
                        f"Dem Team '{team.name}' ist kein Spiel zugeordnet. Bitte ordne dem Team im Teammanager das Spiel '{tournament.game.name}' zu."
                    )
                if tournament.game and team.game != tournament.game:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' ist für das Spiel '{team.game.name}' registriert, das Turnier ist jedoch für '{tournament.game.name}'."
                    )

                # 3.4 Kapitäns-Berechtigung prüfen
                if not is_privileged and not team.is_captain(user):
                    if team.is_member(user):
                        raise TournamentRegistrationError(
                            f"Nur der Kapitän ({team.captain.username}) kann das Team '{team.name}' für ein Turnier anmelden."
                        )
                    else:
                        raise TournamentRegistrationError("Du bist kein Mitglied dieses Teams.")

                # 3.5 Roster-Vollständigkeit & Check-in aller Mitglieder prüfen
                accepted_members = list(team.get_accepted_members())
                if len(accepted_members) < tournament.game.team_size:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' hat nur {len(accepted_members)} von {tournament.game.team_size} erforderlichen Mitgliedern."
                    )
                if len(accepted_members) > tournament.game.team_size:
                    raise TournamentRegistrationError(
                        f"Das Team '{team.name}' hat {len(accepted_members)} Mitglieder. Für '{tournament.game.name}' sind maximal {tournament.game.team_size} Spieler erlaubt."
                    )

                if not is_privileged:
                    for m in accepted_members:
                        if not check_user_event_checkin(m.user, tournament.event):
                            raise TournamentNotCheckedInError(
                                f"Das Teammitglied '{m.user.username}' ist noch nicht am Einlass für '{tournament.event.title}' eingecheckt."
                            )

            # 4. Zeitfenster & Status & Duplikat prüfen
            can_reg, reason = tournament.can_register(user=user, team=team)
            if not can_reg:
                if tournament.status != Tournament.Status.REGISTRATION_OPEN:
                    raise TournamentNotOpenError(reason)
                now = timezone.now()
                if (tournament.registration_start and now < tournament.registration_start) or (tournament.registration_end and now > tournament.registration_end):
                    raise TournamentNotOpenError(reason)
                if tournament.registrations.filter(team=team).exists():
                    raise TournamentAlreadyRegisteredError(reason)
                if tournament.max_teams and tournament.registrations.count() >= tournament.max_teams:
                    raise TournamentFullError(reason)
                raise TournamentRegistrationError(reason)

            # 5. Kapazitätslimit unter DB-Row-Lock prüfen
            current_count = tournament.registrations.select_for_update().count()
            if tournament.max_teams and current_count >= tournament.max_teams:
                raise TournamentFullError(
                    f"Die maximale Teilnehmeranzahl ({tournament.max_teams}) für '{tournament.title}' ist bereits erreicht."
                )

            # 6. Registrierung anlegen
            reg, created = TournamentRegistration.objects.get_or_create(
                tournament=tournament,
                team=team,
            )
            return reg, created

    @staticmethod
    def unregister_team(tournament_id, user, team_id=None, actor=None):
        """
        Meldet ein Team transaktionssicher vom Turnier ab, sofern der Turnierbaum noch nicht generiert wurde.
        """
        with transaction.atomic():
            tournament = Tournament.objects.select_for_update().get(pk=tournament_id)

            if tournament.is_generated or tournament.status in [Tournament.Status.IN_PROGRESS, Tournament.Status.FINISHED]:
                raise TournamentRegistrationError(
                    "Eine Abmeldung ist nicht mehr möglich, da der Turnierbaum bereits generiert wurde oder das Turnier läuft."
                )

            query = TournamentRegistration.objects.filter(tournament=tournament)
            if team_id:
                query = query.filter(team_id=team_id)

            is_privileged = tournament.is_managed_by(actor)

            if not is_privileged:
                query = query.filter(team__memberships__user=user, team__memberships__status=TeamMember.Status.ACCEPTED)

            reg = query.first()
            if not reg:
                raise TournamentRegistrationError("Keine aktive Turnieranmeldung gefunden.")

            team_name = reg.team.name
            reg.delete()
            return team_name
