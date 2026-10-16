from io import StringIO
import json
from pathlib import Path
import stat
import tempfile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class PermissionAuditTests(TestCase):
    def test_effective_rights_sources_and_superusers_without_mutation(self):
        User = get_user_model()
        admin = User.objects.create_superuser('admin', 'private-admin@example.invalid', None)
        direct = User.objects.create_user('direct', 'private-direct@example.invalid', None, is_staff=True)
        grouped = User.objects.create_user('grouped', 'private-group@example.invalid', None, is_staff=True)
        viewer = User.objects.create_user('viewer', 'private-view@example.invalid', None, is_staff=True)
        inactive = User.objects.create_user('inactive', 'private-inactive@example.invalid', None,
                                            is_staff=True, is_active=False)
        permission = Permission.objects.get(content_type__app_label='users', codename='change_user')
        direct.user_permissions.add(permission)
        inactive.user_permissions.add(permission)
        group = Group.objects.create(name='User managers')
        group.permissions.add(permission)
        grouped.groups.add(group)
        before = list(User.objects.values())
        output = StringIO()
        call_command('audit_user_permissions', stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['superusers'], [{'id': admin.pk, 'username': 'admin'}])
        delegated = {item['username']: item for item in result['delegated_user_management']}
        self.assertEqual(set(delegated), {'direct', 'grouped'})
        self.assertTrue(delegated['direct']['direct'])
        self.assertEqual(delegated['grouped']['groups'], [{'id': group.pk, 'name': group.name}])
        self.assertNotIn('@', output.getvalue())
        self.assertEqual(list(User.objects.values()), before)
        self.assertFalse(viewer.user_permissions.exists())

    def test_private_output_never_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.json'
            call_command('audit_user_permissions', output=str(path), stdout=StringIO())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            original = path.read_text()
            with self.assertRaises(CommandError):
                call_command('audit_user_permissions', output=str(path), stdout=StringIO())
            self.assertEqual(path.read_text(), original)
