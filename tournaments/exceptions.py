"""
Spezifische Exceptions für das Turniermodul.
"""


class TournamentError(Exception):
    """Basis-Klasse für alle Turnier-Fehler."""
    pass


class TournamentRegistrationError(TournamentError):
    """Fehler bei der Turnieranmeldung."""
    pass


class TournamentNotOpenError(TournamentRegistrationError):
    """Turnieranmeldung ist aktuell nicht geöffnet oder Zeitfenster ungültig."""
    pass


class TournamentFullError(TournamentRegistrationError):
    """Turnier hat die maximale Teilnehmerzahl erreicht."""
    pass


class TournamentNotCheckedInError(TournamentRegistrationError):
    """Gast ist für das Event nicht eingecheckt."""
    pass


class TournamentAlreadyRegisteredError(TournamentRegistrationError):
    """Team oder Spieler ist bereits für das Turnier angemeldet."""
    pass


class TournamentBracketError(TournamentError):
    """Fehler bei der Turnierbaum-Generierung."""
    pass


class InsufficientTeamsError(TournamentBracketError):
    """Zu wenige Teams für Turnierbaum-Generierung."""
    pass


class BracketAlreadyGeneratedError(TournamentBracketError):
    """Turnierbaum wurde bereits generiert und kann nicht überschrieben werden."""
    pass


class TournamentMatchError(TournamentError):
    """Fehler bei der Match- und Ergebnisverarbeitung."""
    pass


class MatchAlreadyCompletedError(TournamentMatchError):
    """Match ist bereits beendet und Folgematches wurden bereits gestartet/gespielt."""
    pass


class InvalidScoreError(TournamentMatchError):
    """Ungültiger Punktestand."""
    pass


class InvalidWinnerError(TournamentMatchError):
    """Ungültiger oder widersprüchlicher Sieger."""
    pass
