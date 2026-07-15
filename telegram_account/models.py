from django.db import models
from django.utils import timezone


class TelegramAccount(models.Model):
    phone_number = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="phone number",
        help_text="example: +989123456789"
    )
    api_id = models.IntegerField(verbose_name="API ID")
    api_hash = models.CharField(max_length=150, verbose_name="API Hash")

    session_path = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="session path",
        help_text="created automatically"
    )

    is_active = models.BooleanField(
        default=False,
        verbose_name="active(login)"
    )
    is_restricted = models.BooleanField(
        default=False,
        verbose_name="(Spam Block)"
    )
    restricted_until = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="restricted until",
    )

    daily_messages_sent = models.PositiveIntegerField(
        default=0,
        verbose_name="daily messages sent"
    )
    last_message_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="last message sent at"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram Account"
        verbose_name_plural = "Telegram Accounts"
        db_table = "telegram_accounts"

    def __str__(self):
        status = "🟢 active" if self.is_active else "🔴 deactivate"
        if self.is_restricted:
            status = "⚠️ restricted"
        return f"{self.phone_number} | {status}"

    def save(self, *args, **kwargs):
        if not self.session_path:
            clean_phone = self.phone_number.replace("+", "")
            self.session_path = f"sessions/{clean_phone}"
        super().save(*args, **kwargs)

    @property
    def is_ready_to_send(self):
        if not self.is_active:
            return False

        if self.is_restricted:
            if self.restricted_until and timezone.now() > self.restricted_until:
                return True
            return False

        if self.daily_messages_sent >= 25:
            return False

        return True
