import io
import re
import qrcode
from qrcode.constants import ERROR_CORRECT_M

from configuration.models import GeneralConfiguration


def generate_transfer_qr_payload(beneficiary_name, iban, bic, amount, reference):
    """Common EPC payload for individual registrations and fixed clan orders."""
    return '\n'.join([
        'BCD', '002', '1', 'SCT',
        re.sub(r'\s', '', str(bic or '')).upper(),
        re.sub(r'[\r\n]+', ' ', str(beneficiary_name or '')).strip()[:70],
        re.sub(r'[\s\-]', '', str(iban or '')).upper(),
        f'EUR{amount:.2f}' if amount is not None else '', '', '',
        re.sub(r'[\r\n]+', ' ', str(reference or '')).strip()[:140], '',
    ])


def generate_epc_qr_payload(registration, config=None):
    config = config or GeneralConfiguration.load()
    username = registration.user.username if registration.user else ''
    suffix = f" {registration.short_code}" if getattr(registration, 'short_code', None) else f" #{registration.id}"
    return generate_transfer_qr_payload(config.kontoinhaber, config.iban, config.bic,
        registration.effective_price, f'{username}{suffix}')


def _qr_png(payload, box_size=8, border=2):
    qr = qrcode.QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    buffer = io.BytesIO()
    qr.make_image(fill_color='black', back_color='white').save(buffer, format='PNG')
    return buffer.getvalue()


def generate_transfer_qr_png(beneficiary_name, iban, bic, amount, reference):
    return _qr_png(generate_transfer_qr_payload(beneficiary_name, iban, bic, amount, reference))


def generate_epc_qr_png(registration, config=None, box_size=8, border=2):
    return _qr_png(generate_epc_qr_payload(registration, config), box_size, border)


def generate_checkin_qr_png(url, box_size=8, border=2):
    """
    Erzeugt das PNG-Bild eines Check-In QR-Codes im Speicher und liefert die Bytes zurück.
    """
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(url)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return buffer.getvalue()

