from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from configuration.translations import get_translation
from .models import ClanSeatPayment, ClanSeatPaymentLog, ClanSeatHold
from .clan_services import ClanSeatError
from .clan_payments import can_manage_payments, confirm_payment, cancel_payment
from .clan_payment_forms import PaymentActionForm


class PaymentHoldInline(admin.TabularInline):
    model = ClanSeatHold
    fk_name = 'payment'
    extra = 0
    fields = ('seat_label', 'funded_registration', 'state')
    readonly_fields = fields
    can_delete = False

    def has_view_permission(self, request, obj=None):
        return can_manage_payments(request.user)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PaymentLogInline(admin.TabularInline):
    model = ClanSeatPaymentLog
    extra = 0
    fields = ('created_at', 'actor', 'action', 'reason', 'details')
    readonly_fields = fields
    can_delete = False

    def has_view_permission(self, request, obj=None):
        return can_manage_payments(request.user)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ClanSeatPayment)
class ClanSeatPaymentAdmin(admin.ModelAdmin):
    list_display = ('reference', 'allocation', 'seat_count', 'total_amount', 'status', 'payment_due_at', 'release_at', 'manage_link')
    list_filter = ('status', 'allocation__event')
    search_fields = ('reference', 'allocation__clan__name', 'allocation__event__title')
    readonly_fields = tuple(f.name for f in ClanSeatPayment._meta.fields)
    inlines = (PaymentHoldInline, PaymentLogInline)
    actions = None

    def has_view_permission(self, request, obj=None):
        return can_manage_payments(request.user) or super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description='Zahlung verwalten')
    def manage_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse('admin:seating_clanseatpayment_manage', args=[obj.pk]),
            get_translation('clan_payment_admin_confirm'))

    def get_urls(self):
        return [path('<int:payment_id>/manage/', self.admin_site.admin_view(self.manage_view),
                     name='seating_clanseatpayment_manage')] + super().get_urls()

    def manage_view(self, request, payment_id):
        if not can_manage_payments(request.user):
            raise PermissionDenied
        payment = get_object_or_404(ClanSeatPayment.objects.select_related('allocation__clan', 'allocation__event'), pk=payment_id)
        form = PaymentActionForm(request.POST if request.method == 'POST' else None,
            initial={'amount': payment.total_amount, 'received_at': timezone.localtime()})
        if request.method == 'POST' and form.is_valid():
            try:
                if request.POST.get('action') == 'confirm':
                    confirm_payment(payment.pk, request.user.pk, received_at=form.cleaned_data['received_at'],
                        amount=form.cleaned_data['amount'], confirmed=form.cleaned_data['confirmed'])
                    message = 'clan_payment_confirmed'
                elif request.POST.get('action') == 'cancel':
                    cancel_payment(payment.pk, request.user.pk, reason=form.cleaned_data['reason'],
                        confirmed=form.cleaned_data['confirmed'])
                    message = 'clan_payment_cancel_success'
                else:
                    raise ClanSeatError('clan_payment_confirmation_required')
                messages.success(request, get_translation(message))
                return redirect('admin:seating_clanseatpayment_manage', payment_id=payment.pk)
            except ClanSeatError as exc:
                form.add_error(None, str(exc))
        context = {**self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': get_translation('clan_payment_title'), 'payment': payment, 'form': form,
            'holds': payment.holds.select_related('funded_registration__user').order_by('pk')}
        return TemplateResponse(request, 'admin/seating/clan_payment_manage.html', context)


@admin.register(ClanSeatPaymentLog)
class ClanSeatPaymentLogAdmin(admin.ModelAdmin):
    list_display = ('payment', 'created_at', 'actor', 'action', 'reason')
    readonly_fields = tuple(f.name for f in ClanSeatPaymentLog._meta.fields)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
