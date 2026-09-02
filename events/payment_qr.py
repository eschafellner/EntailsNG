import io
import re
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from configuration.models import GeneralConfiguration


def generate_epc_qr_payload(registration, config=None):
    """
    Erzeugt den standardisierten Daten-Payload für einen SEPA Credit Transfer QR-Code
    (GiroCode / EPC-QR-Code nach Standard EPC069-12 Version 002).
    """
    if config is None:
        config = GeneralConfiguration.load()

    service_tag = 'BCD'
    version = '002'
    char_set = '1'  # 1 = UTF-8
    identification = 'SCT'  # SEPA Credit Transfer

    # BIC (optional im SEPA-Raum)
    bic = re.sub(r'\s', '', str(config.bic or '')).upper()

    # Name des Empfängers / Kontoinhabers (max. 70 Zeichen, bereinigt von Zeilenumbrüchen)
    kontoinhaber = re.sub(r'[\r\n]+', ' ', str(config.kontoinhaber or '')).strip()[:70]

    # IBAN des Empfängers (ohne Leerzeichen, Großbuchstaben, max. 34 Zeichen)
    iban = re.sub(r'[\s\-]', '', str(config.iban or '')).upper()

    # Betrag: 'EUR' gefolgt von Betrag mit 2 Dezimalstellen (z.B. EUR15.00)
    # Ist kein Ticket verknüpft, bleibt das Feld leer (Banking-App fragt Betrag ab)
    amount = ''
    if registration.ticket_type and registration.ticket_type.price is not None:
        amount = f"EUR{registration.ticket_type.price:.2f}"

    purpose_code = ''  # Verwendungszweck-Code (z.B. CHAR, leer lassen)
    structured_ref = ''  # Strukturierte Referenz (z.B. ISO 11649 RF-Creditor-Reference, leer lassen)

    # Unstrukturierter Verwendungszweck: Login-Username + Ticket-Code (max. 140 Zeichen, bereinigt von Zeilenumbrüchen)
    username = registration.user.username if registration.user else ''
    ref_suffix = f" {registration.short_code}" if getattr(registration, 'short_code', None) else f" #{registration.id}"
    remittance_raw = f"{username}{ref_suffix}".strip()
    unstructured_remittance = re.sub(r'[\r\n]+', ' ', remittance_raw)[:140]

    beneficiary_info = ''  # Hinweis an Zahler (optional, leer lassen)

    lines = [
        service_tag,
        version,
        char_set,
        identification,
        bic,
        kontoinhaber,
        iban,
        amount,
        purpose_code,
        structured_ref,
        unstructured_remittance,
        beneficiary_info,
    ]

    return '\n'.join(lines)


def generate_epc_qr_png(registration, config=None, box_size=8, border=2):
    """
    Erzeugt das PNG-Bild des GiroCode / EPC-QR-Codes im Speicher und liefert die Bytes zurück.
    """
    payload = generate_epc_qr_payload(registration, config=config)

    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()
