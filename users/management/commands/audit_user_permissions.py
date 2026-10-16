"""Private evidence for USERS-03; deliberately makes no permission changes."""
import json
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Privater Bericht über effektive Benutzerverwaltungsrechte aktiver Staffkonten (USERS-03).'
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--output', help='Neue private JSON-Datei (0600); sonst JSON nach stdout.')

    def handle(self, *args, **options):
        report = {'created_at': timezone.now().isoformat(), 'finding': 'USERS-03',
                  'decision': 'deferred', 'superusers': [], 'delegated_user_management': []}
        users = get_user_model().objects.filter(is_active=True, is_staff=True, is_banned=False,
                                               deleted_at__isnull=True).prefetch_related(
            'user_permissions__content_type', 'groups__permissions__content_type').order_by('pk')
        for user in users:
            identity = {'id': user.pk, 'username': user.username}
            if user.is_superuser:
                report['superusers'].append(identity)
                continue
            direct = any(p.codename == 'change_user' and p.content_type.app_label == 'users'
                         for p in user.user_permissions.all())
            groups = [{'id': group.pk, 'name': group.name} for group in user.groups.all()
                      if any(p.codename == 'change_user' and p.content_type.app_label == 'users'
                             for p in group.permissions.all())]
            if direct or groups:
                report['delegated_user_management'].append({**identity, 'direct': direct, 'groups': groups})
        data = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if options['output']:
            try:
                descriptor = os.open(options['output'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    stream.write(data)
            except OSError:
                raise CommandError('Private Ausgabedatei konnte nicht neu angelegt werden; keine Rechte geändert.') from None
            self.stdout.write('Privater Bericht erstellt; keine Rechte geändert.')
        else:
            self.stdout.write(data, ending='')
