from configuration.translations import get_translation
from django import forms
from django.db import transaction

from tournaments.exceptions import TournamentError
from tournaments.models import TournamentMatch
from tournaments.services.locking import lock_tournament
from tournaments.services.matches import TournamentMatchService


class TournamentMatchAdminForm(forms.ModelForm):
    """Show service validation errors on the admin form before saving results."""
    class Meta:
        model = TournamentMatch
        fields = '__all__'

    def clean(self):
        data = super().clean()
        if self.errors or not self.instance.pk or self.instance.bracket_type == TournamentMatch.BracketType.FFA:
            return data
        fields = ('score_team1', 'score_team2', 'winner', 'decision_reason')
        if not any(field in self.changed_data for field in fields):
            return data
        if data.get('score_team1') is None or data.get('score_team2') is None:
            raise forms.ValidationError(get_translation('audit_score_required', 'Bitte beide Ergebnisse angeben. Gewertete Ergebnisse dürfen nicht gelöscht werden.'))
        winner = data.get('winner')
        try:
            # Admin change forms already run in an outer atomic transaction. Keep
            # event/tournament locks there, while rolling back the trial scoring.
            with transaction.atomic():
                lock_tournament(self.instance.tournament_id)
                with transaction.atomic():
                    TournamentMatchService.update_match_score(self.instance.pk,
                        data['score_team1'], data['score_team2'],
                        winner_id=winner.pk if winner else None,
                        decision_reason=data.get('decision_reason'), actor=self.actor)
                    transaction.set_rollback(True)
        except TournamentError as error:
            raise forms.ValidationError(str(error))
        return data


class TournamentRestartForm(forms.Form):
    title = forms.CharField(max_length=150)
    registration_start = forms.DateTimeField()
    registration_end = forms.DateTimeField()
    tournament_start = forms.DateTimeField(required=False)
    registration_ids = forms.MultipleChoiceField(required=False, widget=forms.CheckboxSelectMultiple)
    copy_seeds = forms.BooleanField(required=False, initial=True)
    cancel_source = forms.BooleanField(required=False)
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))
    preview_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, preview, **kwargs):
        super().__init__(*args, **kwargs)
        for name in self.fields:
            if name != 'preview_token':
                self.fields[name].label = get_translation(f'restart_field_{name}')
        for name in ('registration_start', 'registration_end', 'tournament_start'):
            self.fields[name].widget = forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'})
            self.fields[name].input_formats = ['%Y-%m-%dT%H:%M', *self.fields[name].input_formats]
        self.fields['registration_ids'].choices = [(str(r['id']), r['name']
            + (f" ({get_translation('format_withdrawn')})" if r['withdrawn'] else '')
            + (f" ({get_translation('restart_archived')})" if r['archived'] else ''))
            for r in preview['registrations']]
        self.fields['cancel_source'].disabled = not preview['can_cancel']

    def clean(self):
        data = super().clean()
        if data.get('registration_start') and data.get('registration_end') and data['registration_end'] < data['registration_start']:
            self.add_error('registration_end', get_translation('restart_dates_invalid'))
        return data
