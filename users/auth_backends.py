from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailOrUsernameBackend(ModelBackend):
    """
    Authentifizierungs-Backend, das die Anmeldung sowohl per Benutzername
    als auch per E-Mail-Adresse erlaubt und die 15-Minuten-Account-Sperre nach 5 Fehlversuchen verwaltet.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        # Suche nach Benutzername ODER E-Mail-Adresse (case-insensitive)
        try:
            user = User.objects.get(
                Q(username__iexact=username) | Q(email__iexact=username)
            )
        except User.DoesNotExist:
            # Benutzer existiert nicht -> Aus Sicherheitsgründen keine Info zurückgeben
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(
                Q(username__iexact=username) | Q(email__iexact=username)
            ).first()

        # Prüfe, ob Konto aktuell temporär gesperrt ist (15 Minuten Sperre)
        if user.is_locked():
            # Konto ist gesperrt -> Attribut am Request merken, damit das Formular den Hinweis anzeigen kann
            if request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None

        # Passwort verifizieren
        if user.check_password(password):
            # Passwort korrekt: Login-Sperre/Fehlversuche zurücksetzen & User zurückgeben
            user.reset_lockout()
            return user
        else:
            # Passwort falsch: Fehlversuch registrieren (bei 5 Versuchen -> 15 min Sperre)
            user.register_failed_login()
            if user.is_locked() and request:
                setattr(request, 'account_locked', True)
                setattr(request, 'locked_user', user)
            return None
