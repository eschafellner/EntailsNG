class RegistrationError(Exception):
    """Basis-Exception für Fehler beim Event-Anmeldevorgang."""
    pass


class EventNotOpenError(RegistrationError):
    """Wird geworfen, wenn das Event inaktiv ist oder sich nicht im Status REGISTRATION_OPEN befindet."""
    pass


class EventFullError(RegistrationError):
    """Wird geworfen, wenn max_guests erreicht ist und keine weiteren Plätze frei sind."""
    pass


class RegistrationDeadlinePassedError(RegistrationError):
    """Wird geworfen, wenn der Anmeldeschluss oder das Event-Enddatum verstrichen ist."""
    pass


class InvalidTicketTypeError(RegistrationError):
    """Wird geworfen, wenn ein ungültiger oder inaktiver Tickettyp ausgewählt wurde."""
    pass
