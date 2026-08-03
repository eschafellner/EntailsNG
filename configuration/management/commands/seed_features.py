from django.core.cache import cache
from django.core.management.base import BaseCommand
from configuration.models import FeatureFlag, NavigationItem

DEFAULT_FLAGS = [
    {
        'key': 'onboarding_ticket',
        'name': 'Onboarding Ticket',
        'is_enabled': True,
        'description': 'Zeigt das interaktive Ticket-Widget auf dem Dashboard an.',
    },
    {
        'key': 'seating_module',
        'name': 'Sitzplan-Modul',
        'is_enabled': True,
        'description': 'Aktiviert das Sitzplan- und Reservierungs-Modul im Frontend.',
    },
    {
        'key': 'news_module',
        'name': 'News-Modul',
        'is_enabled': True,
        'description': 'Aktiviert die News-Übersicht und Ankündigungen im Frontend.',
    },
    {
        'key': 'info_module',
        'name': 'Info-Modul',
        'is_enabled': True,
        'description': 'Aktiviert die Detail-Informationsseite zur Veranstaltung.',
    },
    {
        'key': 'clan_module',
        'name': 'Clan-Modul',
        'is_enabled': True,
        'description': 'Aktiviert die Clan-Verwaltung und Clanübersicht im Frontend.',
    },
]

DEFAULT_NAV_ITEMS = [
    {
        'title': 'Dashboard',
        'url_name': 'dashboard',
        'order': 1,
        'icon_svg': (
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>'
            '<polyline points="9 22 9 12 15 12 15 22"></polyline></svg>'
        ),
    },
    {
        'title': 'Sitzplan',
        'url_name': 'seating_plan',
        'order': 2,
        'icon_svg': (
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>'
            '<line x1="3" y1="9" x2="21" y2="9"></line><line x1="9" y1="21" x2="9" y2="9"></line></svg>'
        ),
    },
    {
        'title': 'Infos',
        'url_name': 'event_info_detail',
        'order': 3,
        'icon_svg': (
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle>'
            '<line x1="12" y1="16" x2="12" y2="12"></line>'
            '<line x1="12" y1="8" x2="12.01" y2="8"></line></svg>'
        ),
    },
    {
        'title': 'News',
        'url_name': 'news_list',
        'order': 4,
        'icon_svg': (
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"></path>'
            '<path d="M18 14h-8"></path><path d="M15 18h-5"></path><path d="M10 6h8v4h-8V6Z"></path></svg>'
        ),
    },
    {
        'title': 'Clans',
        'url_name': 'clan_list',
        'order': 5,
        'icon_svg': (
            '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>'
        ),
    },
]


class Command(BaseCommand):
    help = 'Erstellt/Aktualisiert Feature Flags und Hauptnavigation mit SVG-Icons.'

    def handle(self, *args, **options):
        # 1. Feature Flags anlegen
        flags_count = 0
        for flag_data in DEFAULT_FLAGS:
            _, created = FeatureFlag.objects.get_or_create(
                key=flag_data['key'],
                defaults={
                    'name': flag_data['name'],
                    'is_enabled': flag_data['is_enabled'],
                    'description': flag_data['description'],
                },
            )
            if created:
                flags_count += 1

        self.stdout.write(self.style.SUCCESS(f'{flags_count} Feature Flags angelegt.'))

        # 2. Navigation Items anlegen/aktualisieren
        for nav_data in DEFAULT_NAV_ITEMS:
            item, created = NavigationItem.objects.get_or_create(
                title=nav_data['title'],
                defaults={
                    'url_name': nav_data['url_name'],
                    'order': nav_data['order'],
                    'icon_svg': nav_data['icon_svg'],
                    'is_active': True,
                },
            )
            if not created:
                item.url_name = nav_data['url_name']
                item.icon_svg = nav_data['icon_svg']
                item.order = nav_data['order']
                item.is_active = True
                item.save()

        # Auch veraltete NavigationItems mit alten URL-Namen bereinigen, falls vorhanden
        NavigationItem.objects.filter(url_name='seating').update(url_name='seating_plan')
        NavigationItem.objects.filter(url_name='info').update(url_name='event_info_detail')
        NavigationItem.objects.filter(url_name='news').update(url_name='news_list')

        cache.delete('navigation_items')
        cache.delete('feature_flags_dict')

        self.stdout.write(self.style.SUCCESS('Menüpunkte und Icons erfolgreich eingerichtet.'))
