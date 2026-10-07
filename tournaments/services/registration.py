import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .validation import identifier

from events.models import Event, EventRegistration
from tournaments.exceptions import (
    TournamentAlreadyRegisteredError,
    TournamentBracketError,
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


def validate_start_roster(tournament):
    """Revalidate organizer starts after any roster changes since registration.

    Call with the Event/Tournament locks held, before generating any matches.
    Trusted internal imports without an actor retain the legacy service contract.
    """
    from configuration.translations import get_translation
    registrations = list(tournament.registrations.filter(is_forfeited=False).order_by('pk'))
    teams = {team.pk: team for team in Team.objects.select_for_update().filter(
        pk__in=[registration.team_id for registration in registrations]).order_by('pk')}
    seen_users = set()
    problems = []
    for registration in registrations:
        team = teams[registration.team_id]
        members = list(team.get_accepted_members())
        member_ids = {member.user_id for member in members}
        valid = (not team.is_archived and team.game_id == tournament.game_id
            and team.event_id in (None, tournament.event_id)
            and tournament.roster_size_allowed(len(members), for_start=True) and team.captain_id in member_ids
            and all(member.user.is_active and not member.user.deleted_at for member in members)
            and not member_ids.intersection(seen_users))
        if not valid:
            if not tournament.roster_size_allowed(len(members), for_start=True):
                problems.append(get_translation('roster_start_size_problem', team=team.name,
                    count=len(members), size=tournament.game.team_size))
            else:
                problems.append(get_translation('roster_start_team_invalid', team=team.name))
        seen_users.update(member_ids)
    if problems:
        raise TournamentBracketError(get_translation('roster_start_blocked', teams='; '.join(problems)))


def check_user_event_checkin(user, event):
    """
    Prüft, ob der angegebene Benutzer für das aktive Event eingecheckt ist.
    """
    if not user or not user.is_authenticated or not user.is_active or user.is_banned or user.deleted_at or not event:
        return False
    return EventRegistration.objects.filter(
        user=user,
        event=event,
        is_checked_in=True
    ).exclude(payment_status=EventRegistration.PaymentStatus.CANCELLED).exists()


def archive_teams_for_event(event):
    """
    Archiviert alle Teams, die der angegebenen Veranstaltung zugeordnet sind
    oder ohne aktuelle Zuordnung an ihren Turnieren teilgenommen haben.
    Bereits für eine andere Veranstaltung reaktivierte Teams bleiben aktiv.
    """
    if not event:
        return 0
    direct_teams = Team.objects.filter(event=event, is_archived=False)
    tournament_teams = Team.objects.filter(
        tournament_registrations__tournament__event=event,
        event__isnull=True,
        is_archived=False
    )
    combined_ids = set(direct_teams.values_list('id', flat=True)) | set(tournament_teams.values_list('id', flat=True))
    from tournaments.recruitment_signals import expire_invitations
    from tournaments.models import TeamInvitation
    expire_invitations(TeamInvitation.objects.filter(team_id__in=combined_ids))
    count = Team.objects.filter(id__in=combined_ids, is_archived=False).filter(
        Q(event=event) | Q(event__isnull=True)).update(is_archived=True, event=event)
    return count


def _solo_teams(user, game_id):
    return Team.objects.filter(game_id=game_id).filter(
        Q(captain=user) | Q(memberships__user=user, memberships__status=TeamMember.Status.ACCEPTED)
    ).distinct()


def _lock_solo_events(user, game_id, event_id):
    """Lock current and former events before locking the destination tournament.

    The user lock serializes roster changes for this player. Locking former
    events also serializes reactivation with tournament starts and event closure.
    """
    teams = _solo_teams(user, game_id)
    event_ids = set(teams.exclude(event_id=None).values_list('event_id', flat=True))
    event_ids.update(TournamentRegistration.objects.filter(team__in=teams)
        .exclude(tournament__status__in=(Tournament.Status.FINISHED, Tournament.Status.CANCELLED))
        .values_list('tournament__event_id', flat=True))
    if event_id is not None:
        event_ids.add(event_id)
    return {event.pk: event for event in Event.objects.select_for_update()
        .filter(pk__in=event_ids).order_by('pk')}


def _get_or_reactivate_solo_team(user, game, event, locked_events):
    """Call with the player and all relevant event locks already held."""
    from configuration.translations import get_translation

    event_id = event.pk if event else None
    teams = list(Team.objects.select_for_update().filter(
        pk__in=_solo_teams(user, game.pk).values('pk')).order_by('pk'))
    if game.team_size != 1:
        # Preserve the existing technical helper contract for internal callers.
        teams = [team for team in teams if team.is_solo]
    active = [team for team in teams if not team.is_archived]
    if len(active) > 1:
        raise TournamentRegistrationError(get_translation('solo_team_conflict'))
    team = active[0] if active else None
    if team and (team.captain_id != user.pk or team.event_id not in (None, event_id)):
        raise TournamentRegistrationError(get_translation('solo_team_conflict'))

    if not team:
        archived = [team for team in teams if team.is_archived and team.is_solo and team.captain_id == user.pk]
        if event is None:
            archived = [team for team in archived if team.event_id is None]
        # Prefer an archive of the destination event, then the most recently used
        # solo team. Never merge or rewrite other teams' tournament history.
        archived.sort(key=lambda team: (team.event_id == event_id, team.updated_at, -team.pk), reverse=True)
        team = archived[0] if archived else None

    if team:
        if team.event_id is not None and team.event_id not in locked_events:
            raise TournamentRegistrationError(get_translation('audit_team_event_changed'))
        if team.memberships.filter(status=TeamMember.Status.ACCEPTED).exclude(user=user).exists():
            raise TournamentRegistrationError(get_translation('solo_team_invalid_roster'))
        changing_event = team.event_id != event_id
        if (team.is_archived or changing_event) and team.is_in_active_tournament():
            raise TournamentRegistrationError(get_translation('msg_team_reactivate_in_tournament'))
        # An unstarted registration in another open event must not be stranded
        # with a roster belonging to the destination event.
        if changing_event and team.tournament_registrations.exclude(
                tournament__event=event).exclude(tournament__status__in=(
                    Tournament.Status.FINISHED, Tournament.Status.CANCELLED)).exists():
            raise TournamentRegistrationError(get_translation('solo_team_previous_registration'))
        if team.is_archived or changing_event:
            team.event = event
            team.is_archived = False
            team.save(update_fields=['event', 'is_archived', 'updated_at'])

    suffix = ' (Solo)'
    name_limit = Team._meta.get_field('name').max_length
    team_name = user.username[:name_limit-len(suffix)] + suffix
    if not team:
        team = Team.objects.create(
            name=team_name,
            game=game,
            captain=user,
            is_solo=True,
            event=event,
        )
    TeamMember.objects.update_or_create(
        team=team, user=user, defaults={'role': TeamMember.Role.CAPTAIN, 'status': TeamMember.Status.ACCEPTED})
    return team


@transaction.atomic
def get_or_create_solo_team(user, game, event=None):
    """Reuse this account's active team or reactivate its archived solo team."""
    from django.contrib.auth import get_user_model
    from configuration.translations import get_translation
    user = get_user_model().objects.select_for_update(no_key=True).get(pk=user.pk)
    if user.deleted_at or user.is_banned or not user.is_active:
        raise TournamentRegistrationError(get_translation('account_deleted_registration_blocked'))
    locked_events = _lock_solo_events(user, game.pk, event.pk if event else None)
    event = locked_events[event.pk] if event else None
    if event and event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
        raise TournamentNotOpenError(get_translation('msg_tournament_event_finished', event_title=event.title))
    return _get_or_reactivate_solo_team(user, game, event, locked_events)


class TournamentRegistrationService:
    @staticmethod
    def register_team(tournament_id, user, team_id=None, actor=None):
        """
        Meldet ein Team oder einen Solo-Spieler transaktionssicher für ein Turnier an.
        Prüft Zeitfenster, Vor-Ort Check-in, Kapazitätslimits und Team-Berechtigungen.
        """
        with transaction.atomic():
            from django.contrib.auth import get_user_model
            from configuration.translations import get_translation
            user = get_user_model().objects.select_for_update(no_key=True).get(pk=user.pk)
            if user.deleted_at or user.is_banned or not user.is_active:
                raise TournamentRegistrationError(get_translation('account_deleted_registration_blocked'))
            # Nach dem User sperren Turnieranmeldungen dieselbe Event-Zeile wie der Eventabschluss.
            # So kann keine Turnieranmeldung zwischen Abschlussprüfung und Archivierung erfolgen.
            event_id, game_id, team_size = Tournament.objects.values_list(
                'event_id', 'game_id', 'game__team_size').get(pk=tournament_id)
            locked_events = _lock_solo_events(user, game_id, event_id) if team_size == 1 else None
            event = locked_events[event_id] if locked_events is not None else Event.objects.select_for_update().get(pk=event_id)
            if event.effective_status in (Event.Status.FINISHED, Event.Status.CANCELLED):
                from configuration.translations import get_translation
                raise TournamentNotOpenError(get_translation(
                    'msg_tournament_event_finished',
                    'Die Veranstaltung "{event_title}" ist beendet oder abgesagt. Eine Turnieranmeldung ist nicht mehr möglich.',
                    event_title=event.title,
                ))

            tournament = Tournament.objects.select_for_update().select_related('game', 'event').get(pk=tournament_id)
            if (tournament.event_id, tournament.game_id, tournament.game.team_size) != (event_id, game_id, team_size):
                raise TournamentRegistrationError(get_translation('audit_team_event_changed'))

            # 1. Privilegien-Check (Staff / Superuser / Turnier-Admin)
            is_privileged = tournament.is_managed_by(actor)

            # 2. Vor-Ort Check-in des anmeldenden Benutzers prüfen
            if not is_privileged and not check_user_event_checkin(user, tournament.event):
                raise TournamentNotCheckedInError(
                    "Nur vor Ort eingecheckte Gäste können sich für Turniere anmelden! Bitte checke zuerst am Einlass ein."
                )

            # 3. Team bestimmen / Solo-Team erzeugen
            if tournament.game.team_size == 1:
                team = _get_or_reactivate_solo_team(user, tournament.game, event, locked_events)
            else:
                if not team_id:
                    raise TournamentRegistrationError("Bitte wähle ein Team für die Anmeldung aus.")
                team = Team.objects.select_for_update().filter(id=identifier(team_id, error=TournamentRegistrationError)).first()
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
                if any(member.user.deleted_at or member.user.is_banned for member in accepted_members):
                    raise TournamentRegistrationError(get_translation('account_deleted_roster_blocked'))
                if not accepted_members:
                    raise TournamentRegistrationError(get_translation('roster_empty', team=team.name))
                if len(accepted_members) < tournament.game.team_size and not tournament.roster_size_allowed(len(accepted_members)):
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
                query = query.filter(team_id=identifier(team_id, error=TournamentRegistrationError))

            is_privileged = tournament.is_managed_by(actor)

            if not is_privileged:
                query = query.filter(team__memberships__user=user, team__memberships__status=TeamMember.Status.ACCEPTED)

            reg = query.first()
            if not reg:
                raise TournamentRegistrationError("Keine aktive Turnieranmeldung gefunden.")

            team_name = reg.team.name
            reg.delete()
            return team_name
