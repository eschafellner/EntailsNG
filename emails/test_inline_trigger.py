from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from . import services


@override_settings(IS_TESTING=False)
class InlineQueueTriggerTests(SimpleTestCase):
    """F-021: Standardmäßig versendet nur der Mail-Worker, nicht ein Thread im Webprozess."""

    def test_no_thread_by_default(self):
        with patch.object(services.threading, 'Thread') as thread:
            services.trigger_queue_processing()
        thread.assert_not_called()

    @override_settings(EMAIL_INLINE_TRIGGER=True, IS_TESTING=False)
    def test_optional_thread_closes_its_connection(self):
        with patch.object(services.threading, 'Thread') as thread, \
                patch.object(services.transaction, 'get_connection') as get_connection:
            get_connection.return_value.in_atomic_block = False
            services.trigger_queue_processing()
        thread.assert_called_once()
        target = thread.call_args.kwargs['target']
        with patch.object(services, 'process_email_queue') as process, \
                patch.object(services.connection, 'close') as close:
            target()
        process.assert_called_once_with(limit=25)
        close.assert_called_once()
