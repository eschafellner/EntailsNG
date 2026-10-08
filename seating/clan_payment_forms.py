from django import forms
from configuration.translations import get_translation


class CreatePaymentForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput)
    event_id = forms.IntegerField(widget=forms.HiddenInput)
    confirmed = forms.BooleanField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['confirmed'].label = get_translation('clan_payment_confirm_lock')


class AssignmentForm(forms.Form):
    user_id = forms.IntegerField(required=False)
    expected_registration_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    confirmed = forms.BooleanField()
    reason = forms.CharField(required=False, max_length=2000)


class PaymentActionForm(forms.Form):
    received_at = forms.DateTimeField(required=False, widget=forms.DateTimeInput(
        attrs={'type': 'datetime-local', 'step': '1'}, format='%Y-%m-%dT%H:%M:%S'))
    amount = forms.DecimalField(required=False, max_digits=10, decimal_places=2, min_value=0)
    reason = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))
    confirmed = forms.BooleanField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field, key in [('received_at', 'clan_payment_received_at'), ('amount', 'clan_payment_received_amount'),
                           ('reason', 'clan_payment_reason'), ('confirmed', 'clan_payment_received_confirm')]:
            self.fields[field].label = get_translation(key)
