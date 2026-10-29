from email.utils import getaddresses

from django.core import mail
from django.test import TestCase

from .backends import ConfiguredSMTPBackend
from .models import GeneralEmailSettings


class SenderHeaderTests(TestCase):
    """F-023: Absendernamen mit Sonderzeichen ergeben genau eine gültige Mailbox."""

    def test_comma_in_sender_name_yields_single_mailbox(self):
        cfg = GeneralEmailSettings.load()
        cfg.sender_email = 'orga@lan.example'
        for name in ('Orga, LAN e.V.', 'Orga "LAN" <Team>', 'Müller & Söhne'):
            with self.subTest(name=name):
                cfg.sender_name = name
                msg = mail.EmailMessage(subject='x', body='y', to=['gast@example.com'])
                ConfiguredSMTPBackend._apply_sender(cfg, [msg])
                header = msg.message()['From']
                addresses = getaddresses([str(header)])
                self.assertEqual(len(addresses), 1, header)
                self.assertEqual(addresses[0][1], 'orga@lan.example')
