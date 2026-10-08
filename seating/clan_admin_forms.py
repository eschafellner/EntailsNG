"""Explicit release selection when the Orga lowers a quota."""
from django import forms
from clans.models import Clan
from configuration.models import ClanSeatConfiguration
from .clan_services import open_holds, release_holds
from .models import ClanSeatHold


class QuotaReleaseForm(forms.ModelForm):
    # Declared fields are needed for Django admin's ModelForm factory.
    release_seats = forms.MultipleChoiceField(required=False)
    confirm_release = forms.BooleanField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = open_holds().filter(payment__isnull=True).select_related('allocation__clan', 'allocation__event')
        if isinstance(self.instance, Clan):
            qs = qs.filter(allocation__clan_id=self.instance.pk)
        self.available_holds = list(qs.order_by('allocation_id', 'pk'))
        self.fields['release_seats'] = forms.MultipleChoiceField(
            required=False, widget=forms.CheckboxSelectMultiple,
            label='Offene Vormerkungen zur Freigabe auswählen',
            choices=[(str(h.pk), f'{h.allocation.clan.name} / {h.allocation.event.title}: {h.seat_label}') for h in self.available_holds],
            help_text='Bei einer Kontingentreduzierung die freizugebenden Plätze auswählen. Persönliche Buchungen bleiben erhalten.',
        )
        self.fields['confirm_release'] = forms.BooleanField(
            required=False, label='Freigabe der angezeigten bzw. ausgewählten offenen Clan-Vormerkungen bestätigen',
            help_text='Bei Deaktivierung oder Kontingent 0 werden offene Vormerkungen ohne Sammelauftrag freigegeben. Festgeschriebene Sammelaufträge bleiben erhalten.',
        )

    def clean(self):
        data = super().clean()
        config = ClanSeatConfiguration.load()
        is_clan = isinstance(self.instance, Clan)
        enabled = config.enabled if is_clan else data.get('enabled', config.enabled)
        default = config.default_limit if is_clan else data.get('default_limit', config.default_limit)
        override = data.get('seat_limit_override') if is_clan else None
        selected = set(data.get('release_seats', []))
        groups = {}
        for hold in self.available_holds:
            groups.setdefault(hold.allocation_id, []).append(hold)
        auto_ids = set()
        for holds in groups.values():
            clan = holds[0].allocation.clan
            limit = (default if override is None else override) if is_clan else (default if clan.seat_limit_override is None else clan.seat_limit_override)
            if not enabled or limit == 0:
                auto_ids.update(str(h.pk) for h in holds)
                continue
            remaining = [h for h in holds if str(h.pk) not in selected]
            consumed = holds[0].allocation.holds.filter(state=ClanSeatHold.State.CLAIMED).exclude(pk__in=[h.pk for h in remaining]).count()
            if remaining and len(remaining) + consumed > limit:
                self.add_error('release_seats', f'{clan.name}: Bitte genügend offene Plätze auswählen, um das neue Kontingent {limit} einzuhalten. Bereits übernommene Plätze bleiben erhalten.')
        self.release_ids = selected | auto_ids
        if self.release_ids and not data.get('confirm_release'):
            self.add_error('confirm_release', 'Bitte die Freigabe ausdrücklich bestätigen.')
        return data

    def apply_releases(self):
        release_holds(ClanSeatHold.objects.filter(pk__in=self.release_ids))


class ClanSeatConfigurationForm(QuotaReleaseForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ('payment_days', 'payment_review_days'):
            self.fields[field].required = False

    def clean(self):
        data = super().clean()
        for field in ('payment_days', 'payment_review_days'):
            if data.get(field) is None:
                data[field] = getattr(self.instance, field)
        return data

    class Meta:
        model = ClanSeatConfiguration
        fields = '__all__'


class ClanQuotaForm(QuotaReleaseForm):
    class Meta:
        model = Clan
        fields = '__all__'
