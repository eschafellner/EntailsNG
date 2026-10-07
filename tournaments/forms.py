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

    result_version = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            from .services.results import match_version
            self.fields['result_version'].initial = match_version(self.instance)

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
                        decision_reason=data.get('decision_reason'), actor=self.actor,
                        expected_state=data.get('result_version') or None)
                    transaction.set_rollback(True)
        except TournamentError as error:
            raise forms.ValidationError(str(error))
        return data


class MatchResultForm(forms.Form):
    score_team1 = forms.IntegerField(min_value=0, max_value=2**31-1)
    score_team2 = forms.IntegerField(min_value=0, max_value=2**31-1)
    winner_id = forms.ChoiceField(required=False)
    decision_reason = forms.CharField(required=False, max_length=255)
    expected_state = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, match, **kwargs):
        from .services.results import match_version
        kwargs.setdefault('auto_id', f'match_{match.pk}_%s')
        super().__init__(*args, **kwargs)
        for name in ('score_team1', 'score_team2'):
            self.fields[name].label = match.team1.name if name == 'score_team1' and match.team1 else match.team2.name if match.team2 else name
            self.fields[name].initial = getattr(match, name)
        self.fields['winner_id'].choices = [('', get_translation('tournament_modal_winner_auto'))] + [
            (str(team.pk), team.name) for team in (match.team1, match.team2) if team]
        self.fields['winner_id'].initial = match.winner_id or ''
        self.fields['winner_id'].label = get_translation('tournament_modal_select_winner_label')
        self.fields['decision_reason'].label = get_translation('results_reason' if match.status == TournamentMatch.Status.COMPLETED else 'tournament_modal_reason_label')
        self.fields['decision_reason'].required = match.status == TournamentMatch.Status.COMPLETED
        self.fields['expected_state'].initial = match_version(match)


class TournamentAdminForm(forms.ModelForm):
    class Meta:
        from .models import Tournament
        model = Tournament
        fields = '__all__'

    def clean_status(self):
        from .models import Tournament
        status = self.cleaned_data['status']
        if self.instance.pk:
            old = Tournament.objects.get(pk=self.instance.pk).status
            if status != old and (status in (Tournament.Status.RESULTS_REVIEW, Tournament.Status.FINISHED)
                    or old in (Tournament.Status.FINISHED, Tournament.Status.CANCELLED)
                    or (old == Tournament.Status.RESULTS_REVIEW and status != Tournament.Status.CANCELLED)):
                raise forms.ValidationError(get_translation('results_use_actions'))
        elif status in (Tournament.Status.RESULTS_REVIEW, Tournament.Status.FINISHED):
            raise forms.ValidationError(get_translation('results_use_actions'))
        return status


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
