from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from common.models import BaseModel


class MessageType(models.TextChoices):
    TEXT = 'TEXT', _('Text Message')
    VOICE = 'VOICE', _('Voice Note')
    # PHOTO = 'PHOTO', _('Photo')


class MessageTemplate(BaseModel):
    """
    Reusable message templates (Text or Voice) to be sent to targets.
    """
    title = models.CharField(
        max_length=255,
        verbose_name=_("Template Title"),
        help_text=_("Internal name for this template.")
    )
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT,
        verbose_name=_("Message Type")
    )

    # Text Content
    text_content = models.TextField(
        blank=True,
        verbose_name=_("Text Content"),
        help_text=_("The message text. Can also be used as a caption for voice/media.")
    )

    # Voice File Handling
    voice_file = models.FileField(
        upload_to='sender/voices/',
        blank=True,
        null=True,
        verbose_name=_("Voice File (.ogg)"),
        help_text=_("Must be an .ogg file with OPUS codec for Telegram Voice Notes.")
    )
    telegram_file_id = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Telegram File ID"),
        help_text=_("Auto-filled after the first upload to prevent re-uploading and spam flags.")
    )

    class Meta:
        verbose_name = _("Message Template")
        verbose_name_plural = _("Message Templates")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_message_type_display()})"

    def clean(self):
        super().clean()
        if self.message_type == MessageType.TEXT and not self.text_content:
            raise ValidationError({"text_content": _("Text content is required for Text messages.")})

        if self.message_type == MessageType.VOICE and not self.voice_file and not self.telegram_file_id:
            raise ValidationError({"voice_file": _("A voice file is required for Voice messages.")})


class SenderTaskStatus(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    PROCESSING = 'PROCESSING', _('Processing')
    COMPLETED = 'COMPLETED', _('Completed')
    FAILED = 'FAILED', _('Failed')
    PAUSED = 'PAUSED', _('Paused')


class SenderTask(BaseModel):
    """
    The main campaign model that links execution accounts, target filters, and messages.
    """
    title = models.CharField(
        max_length=255,
        verbose_name=_("Campaign Title")
    )

    # 1. Execution Settings
    execution_accounts = models.ManyToManyField(
        'telegram_account.TelegramAccount',
        blank=True,
        related_name="sender_tasks",
        verbose_name=_("Execution Accounts"),
        help_text=_("Accounts to rotate for sending messages. If empty, the system can auto-select active ones.")
    )

    # 2. Target Filters
    target_sources = models.ManyToManyField(
        'crawler.TelegramSource',
        related_name="sender_tasks",
        verbose_name=_("Target Sources"),
        help_text=_("Only send to users extracted from these groups/channels.")
    )
    only_premium_users = models.BooleanField(
        default=False,
        verbose_name=_("Only Premium Users"),
        help_text=_("Target only Telegram Premium users.")
    )

    # 3. Message Configuration (using intermediate model for ordering)
    messages = models.ManyToManyField(
        MessageTemplate,
        through='TaskMessage',
        related_name='sender_tasks',
        verbose_name=_("Messages to Send")
    )

    # 4. Limits and Delays (Crucial for Anti-Spam)
    daily_limit_per_account = models.PositiveIntegerField(
        default=25,
        verbose_name=_("Daily Limit Per Account"),
        help_text=_("Max messages an account will send per day before resting.")
    )
    delay_between_messages = models.PositiveIntegerField(
        default=60,
        verbose_name=_("Base Delay (Seconds)"),
        help_text=_("Base delay between messages. System will add random jitter to this.")
    )

    # 5. Status Tracking
    status = models.CharField(
        max_length=20,
        choices=SenderTaskStatus.choices,
        default=SenderTaskStatus.PENDING,
        db_index=True,
        verbose_name=_("Status")
    )
    users_messaged = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Total Users Messaged")
    )

    class Meta:
        verbose_name = _("Sender Task")
        verbose_name_plural = _("Sender Tasks")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} | Status: {self.status}"


class TaskMessage(BaseModel):
    """
    Intermediate model to handle the order of messages sent in a campaign.
    e.g., Order 1: Text Greeting, Order 2: Voice Note.
    """
    task = models.ForeignKey(SenderTask, on_delete=models.CASCADE)
    message_template = models.ForeignKey(MessageTemplate, on_delete=models.CASCADE)
    order = models.PositiveIntegerField(
        default=1,
        verbose_name=_("Sending Order"),
        help_text=_("1 is sent first, 2 is sent second, etc.")
    )

    class Meta:
        verbose_name = _("Task Message")
        verbose_name_plural = _("Task Messages")
        ordering = ['task', 'order']
        # Prevent assigning the exact same order number to two messages in the same task
        unique_together = ('task', 'order')

    def __str__(self):
        return f"{self.task.title} - Msg {self.order}: {self.message_template.title}"
