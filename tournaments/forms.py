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
