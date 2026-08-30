import re
from django.core.exceptions import ValidationError


def validate_iban(value):
    """
    Validiert eine internationale Bankkontonummer (IBAN) gemäß ISO 13616 und ISO 7064 (MOD 97-10).
    Akzeptiert Eingaben mit oder ohne Leerzeichen/Bindestriche.
    """
    if not value:
        return

    # Leerzeichen und Trennstriche entfernen, Großschreibung
    clean_iban = re.sub(r'[\s\-]', '', str(value)).upper()

    if len(clean_iban) < 15 or len(clean_iban) > 34:
        raise ValidationError(
            f"Ungültige IBAN-Länge: Eine IBAN muss zwischen 15 und 34 Zeichen lang sein (eingegeben: {len(clean_iban)} Zeichen)."
        )

    # Prüfen, ob die ersten beiden Zeichen ein Ländercode sind und der Rest alphanumerisch ist
    if not re.match(r'^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$', clean_iban):
        raise ValidationError(
            "Ungültiges IBAN-Format: Eine IBAN muss mit einem 2-stelligen Ländercode und 2 Prüfziffern beginnen."
        )

    # ISO 7064 MOD 97-10 Prüfziffern-Algorithmus:
    # 1. Erste 4 Zeichen ans Ende verschieben
    rearranged = clean_iban[4:] + clean_iban[:4]

    # 2. Buchstaben durch entsprechende Zahlenwerte ersetzen (A=10, B=11, ..., Z=35)
    numeric_string = ''
    for char in rearranged:
        if char.isdigit():
            numeric_string += char
        else:
            numeric_string += str(ord(char) - 55)

    # 3. Ganzzahlige Modulo-97-Division: Bei gültiger IBAN muss der Rest genau 1 sein
    if int(numeric_string) % 97 != 1:
        raise ValidationError(
            "Ungültige IBAN: Die mathematische Prüfsumme (ISO 7064 MOD 97-10) stimmt nicht überein."
        )


def validate_bic(value):
    """
    Validiert einen BIC/SWIFT-Code (8 oder 11 Zeichen nach ISO 9362).
    """
    if not value:
        return

    clean_bic = re.sub(r'\s', '', str(value)).upper()

    if not re.match(r'^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$', clean_bic):
        raise ValidationError(
            "Ungültiger BIC / SWIFT-Code: Muss aus 8 oder 11 alphanumerischen Zeichen bestehen (z. B. GENODEF1S01)."
        )
