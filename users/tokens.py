from django.contrib.auth.tokens import PasswordResetTokenGenerator


class ModerationPasswordResetTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        original = super()._make_hash_value(user, timestamp)
        # Keep pre-migration links valid for accounts without an organizer ban.
        return original if not user.session_version else f'{original}:{user.session_version}'


password_reset_token_generator = ModerationPasswordResetTokenGenerator()
