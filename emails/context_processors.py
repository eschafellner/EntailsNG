def email_status(request):
    """Stellt einen Warnhinweis für Staff-Nutzer bereit, wenn kein Versand möglich ist oder Sandbox aktiv ist."""
    if not (hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff):
        return {}
    try:
        from .models import GeneralEmailSettings
        cfg = GeneralEmailSettings.load()
    except Exception:
        return {}
    if cfg.is_operational and not cfg.is_sandbox:
        return {}
    return {
        'email_warning': cfg.blocking_reason,
        'email_warning_is_info': bool(cfg.is_sandbox and cfg.is_operational),
    }
