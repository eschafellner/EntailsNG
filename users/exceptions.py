class VerificationCodeError(Exception):
    """Basis-Exception für Fehler bei der Erzeugung oder Validierung von Verifizierungscodes."""
    pass


class VerificationCodeCooldownError(VerificationCodeError):
    """Wird geworfen, wenn ein neuer Code innerhalb des Cooldown-Fensters angefordert wird."""

    def __init__(self, message="Bitte warte kurz, bevor du einen neuen Code anforderst.", retry_after=60):
        super().__init__(message)
        self.retry_after = retry_after


class VerificationCodeLimitError(VerificationCodeError):
    """Wird geworfen, wenn das Stundenlimit für Bestätigungscodes erreicht ist."""
    pass
