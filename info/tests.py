from django.test import TestCase
from django.urls import reverse
from info.models import EventInfo


class EventInfoViewTests(TestCase):

    def setUp(self):
        self.info = EventInfo.objects.create(
            title='LAN Info & Regeln',
            subtitle='Alles Wichtige',
            content='<p>WLAN Passwort & Catering Infos</p>',
        )

    def test_event_info_detail_view(self):
        response = self.client.get(reverse('event_info_detail'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LAN Info &amp; Regeln')
        self.assertContains(response, 'WLAN Passwort & Catering Infos')
