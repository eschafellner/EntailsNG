import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from seating.models import SeatingCell, SeatingPlan
from seating.services import SeatingPlanService, SeatingPlanValidationError

User = get_user_model()


class SeatingLabelWhitelistTests(TestCase):
    """F-034: Sitz- und Beschriftungstexte nur aus unkritischen Zeichen."""

    @classmethod
    def setUpTestData(cls):
        cls.event = Event.objects.create(
            title='Label LAN', slug='label-lan', status=Event.Status.REGISTRATION_OPEN,
            start_date=timezone.now() + timedelta(days=5), end_date=timezone.now() + timedelta(days=7),
        )
        cls.plan = SeatingPlan.objects.create(event=cls.event, name='Halle', columns=5, rows=5)
        cls.admin = User.objects.create_superuser('label_admin', 'label@example.com', 'password')

    def test_save_grid_rejects_markup_and_quotes_in_seat_label(self):
        for label in ["',import('//a.bc'),'", '<svg onload=alert()>', 'A"1', 'A`1', 'A\\1', 'A=1']:
            with self.subTest(label=label), self.assertRaises(SeatingPlanValidationError):
                SeatingPlanService.save_grid(self.plan, [
                    {'x': 1, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': label},
                ])
        self.assertFalse(self.plan.cells.exists())

    def test_save_grid_rejects_markup_in_text_label(self):
        for label in ['<b>Bühne</b>', "Bar'", 'x" onmouseover="y']:
            with self.subTest(label=label), self.assertRaises(SeatingPlanValidationError):
                SeatingPlanService.save_grid(self.plan, [
                    {'x': 1, 'y': 1, 'cell_type': SeatingCell.CellType.LABEL, 'text_label': label},
                ])
        self.assertFalse(self.plan.cells.exists())

    def test_save_grid_accepts_usual_labels(self):
        seats = ['A1', 'A-01', 'Reihe 1 / Platz 1', 'R1-P1', 'VIP #3', 'Süd_2.1']
        texts = ['Bühne', 'Ein-/Ausgang', 'Getränke & Snacks', 'Technik (Süd)', 'Bar: 18-2 Uhr!', 'Info, WC?', 'Stand +1']
        cells = [
            {'x': x, 'y': 1, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': label}
            for x, label in enumerate(seats[:5], start=1)
        ] + [
            {'x': x, 'y': 2, 'cell_type': SeatingCell.CellType.LABEL, 'text_label': label}
            for x, label in enumerate(texts[:5], start=1)
        ] + [
            {'x': 1, 'y': 3, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': seats[5]},
            {'x': 1, 'y': 4, 'cell_type': SeatingCell.CellType.LABEL, 'text_label': texts[5]},
            {'x': 2, 'y': 4, 'cell_type': SeatingCell.CellType.LABEL, 'text_label': texts[6]},
        ]
        SeatingPlanService.save_grid(self.plan, cells)
        self.assertEqual(sorted(self.plan.cells.exclude(seat_label='').values_list('seat_label', flat=True)), sorted(seats))
        self.assertEqual(sorted(self.plan.cells.exclude(text_label='').values_list('text_label', flat=True)), sorted(texts))

    def test_model_validation_covers_admin_forms(self):
        cell = SeatingCell(plan=self.plan, x=1, y=1, cell_type=SeatingCell.CellType.SEAT, seat_label='<svg onload=alert()>')
        with self.assertRaises(ValidationError) as ctx:
            cell.full_clean()
        self.assertIn('seat_label', ctx.exception.message_dict)
        cell.seat_label = 'A1'
        cell.text_label = '<script>'
        with self.assertRaises(ValidationError) as ctx:
            cell.full_clean()
        self.assertIn('text_label', ctx.exception.message_dict)

    def test_editor_api_returns_error_for_invalid_label(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse('save_seating_plan', kwargs={'plan_id': self.plan.id}),
            data=json.dumps({'cells': [
                {'x': 2, 'y': 3, 'cell_type': SeatingCell.CellType.SEAT, 'seat_label': '<svg onload=alert()>'},
            ], 'version': self.plan.version}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('(2,3)', response.json()['message'])
        self.assertFalse(self.plan.cells.exists())


class SeatingEditorContextTests(TestCase):
    """F-030: Der Editor übergibt die Zellen nur noch per json_script (cells_data)."""

    def test_editor_context_has_no_unused_cells_json(self):
        start = timezone.now() + timedelta(days=5)
        event = Event.objects.create(title='Editor LAN', slug='editor-lan', status=Event.Status.REGISTRATION_OPEN,
                                     start_date=start, end_date=start + timedelta(days=1))
        plan = SeatingPlan.objects.create(event=event, name='Halle', columns=2, rows=2)
        self.client.force_login(User.objects.create_superuser('editor_admin', 'editor@example.com', 'password'))
        response = self.client.get(reverse('seating_editor', kwargs={'plan_id': plan.id}))
        self.assertEqual(response.status_code, 200)
        self.assertIn('cells_data', response.context)
        self.assertNotIn('cells_json', response.context)
