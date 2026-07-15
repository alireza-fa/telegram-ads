from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.exceptions import ValidationError

from common.models import BaseModel


class SourceChatType(models.TextChoices):
    GROUP = 'GROUP', _('Group / Supergroup')
    CHANNEL = 'CHANNEL', _('Channel')


class TelegramSource(BaseModel):
    """
    Model to store and manage target groups or channels as sources for marketing.
    """
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Chat Title"),
        help_text=_("Name of the group/channel for easy identification.")
    )

    # One of these must be provided
    link = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Link or Username"),
        help_text=_("Public username (@group) or private invite link.")
    )
    telegram_id = models.BigIntegerField(
        null=True,
        blank=True,
        unique=True,
        verbose_name=_("Telegram Chat ID"),
        help_text=_("Internal Telegram ID if resolved.")
    )

    chat_type = models.CharField(
        max_length=20,
        choices=SourceChatType.choices,
        default=SourceChatType.GROUP,
        verbose_name=_("Chat Type")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active"),
        help_text=_("Uncheck to stop crawling or messaging users from this source.")
    )

    last_crawled_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Crawled At")
    )

    class Meta:
        verbose_name = _("Telegram Source")
        verbose_name_plural = _("Telegram Sources")
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.link


class CrawlerTaskStatus(models.TextChoices):
    PENDING = 'PENDING', _('Pending')
    PROCESSING = 'PROCESSING', _('Processing')
    COMPLETED = 'COMPLETED', _('Completed')
    FAILED = 'FAILED', _('Failed')
    PAUSED = 'PAUSED', _('Paused')


class CrawlerSourceType(models.TextChoices):
    GROUP_HISTORY = 'GROUP_HISTORY', _('Group History (Messages)')
    CHANNEL_COMMENTS = 'CHANNEL_COMMENTS', _('Channel Comments')
    # GROUP_PARTICIPANTS = 'GROUP_PARTICIPANTS', _('Group Participants List')


class CrawlerTask(BaseModel):
    """
    Model to track and manage background crawling tasks for Telegram targets.
    """
    # 1. Execution Context
    execution_account = models.ForeignKey(
        'telegram_account.TelegramAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crawler_tasks",
        verbose_name=_("Execution Account"),
        help_text=_("The Telegram account used to run this crawler.")
    )

    # 2. Target Configuration
    source = models.ForeignKey(
        'crawler.TelegramSource',
        on_delete=models.CASCADE,
        related_name="crawler_tasks",
        verbose_name=_("Target Source"),
        help_text=_("The group or channel to crawl.")
    )

    crawl_method = models.CharField(
        max_length=50,
        choices=CrawlerSourceType.choices,
        default=CrawlerSourceType.GROUP_HISTORY,
        verbose_name=_("Crawl Method")
    )

    # 3. Limits and Filters
    target_user_count = models.PositiveIntegerField(
        default=100,
        verbose_name=_("Target User Count"),
        help_text=_("Stop crawling when this many unique users are extracted.")
    )
    message_scan_limit = models.PositiveIntegerField(
        default=10000,
        verbose_name=_("Message Scan Limit"),
        help_text=_("Stop crawling after traversing this many messages, regardless of user count.")
    )
    include_admins = models.BooleanField(
        default=False,
        verbose_name=_("Include Admins"),
        help_text=_("If False, attempts to skip group administrators (if detectable).")
    )

    # 4. Status and Retry Management
    status = models.CharField(
        max_length=20,
        choices=CrawlerTaskStatus.choices,
        default=CrawlerTaskStatus.PENDING,
        db_index=True,
        verbose_name=_("Status")
    )
    error_message = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Error Message")
    )
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Attempt Count")
    )
    max_attempts = models.PositiveIntegerField(
        default=3,
        verbose_name=_("Max Attempts")
    )

    # 5. Progress Tracking (Crucial for resuming tasks)
    users_crawled = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Users Crawled"),
        help_text=_("Current count of successfully extracted users.")
    )
    messages_scanned = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Messages Scanned"),
        help_text=_("Current count of messages traversed in this task.")
    )
    last_message_id = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Last Message ID"),
        help_text=_("ID of the last message processed. Used to resume crawling.")
    )

    # 6. Timestamps
    started_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Started At"))
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Completed At"))

    class Meta:
        verbose_name = _("Crawler Task")
        verbose_name_plural = _("Crawler Tasks")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["execution_account", "status"]),
        ]

    def __str__(self):
        # FIXED: target_link replaced with source.link
        target = self.source.link if self.source else "No Source"
        return f"CrawlerTask<{target} | Status: {self.status}>"

    def clean(self):
        super().clean()

        if self.target_user_count <= 0:
            raise ValidationError({"target_user_count": _("Target user count must be greater than zero.")})

        if self.message_scan_limit <= 0:
            raise ValidationError({"message_scan_limit": _("Message scan limit must be greater than zero.")})

        if self.status == CrawlerTaskStatus.PROCESSING and self.completed_at:
            raise ValidationError({"completed_at": _("Processing task cannot have completed_at set.")})

        if self.status == CrawlerTaskStatus.COMPLETED and not self.completed_at:
            raise ValidationError({"completed_at": _("Completed task must have a completed_at timestamp.")})

    def mark_processing(self):
        self.status = CrawlerTaskStatus.PROCESSING
        self.started_at = timezone.now()
        self.attempt_count += 1
        self.save(update_fields=["status", "started_at", "attempt_count", "updated_at"])

    def mark_failed(self, message: str):
        self.status = CrawlerTaskStatus.FAILED
        self.error_message = message or ""
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at", "updated_at"])

    def mark_completed(self):
        self.status = CrawlerTaskStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])


class TargetUserStatus(models.TextChoices):
    PENDING = 'PENDING', _('Pending (Ready to message)')
    IN_QUEUE = 'IN_QUEUE', _('In Queue for messaging')
    MESSAGED = 'MESSAGED', _('Message Sent')
    REPLIED = 'REPLIED', _('Replied (Engaged)')
    FAILED = 'FAILED', _('Failed to send (Blocked/Privacy)')


class CrawledUser(BaseModel):
    """
    Model to store extracted Telegram users (Marketing Leads).
    """
    # 1. Telegram Identifiers
    telegram_id = models.BigIntegerField(
        unique=True,
        verbose_name=_("Telegram ID")
    )
    username = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_("Username"),
        help_text=_("Without @ symbol. Can be null if user has no username.")
    )

    # 2. Profile Information
    first_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("First Name")
    )
    last_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Last Name")
    )
    phone_number = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name=_("Phone Number")
    )

    # 3. Metadata from Telegram
    is_premium = models.BooleanField(
        default=False,
        verbose_name=_("Is Premium")
    )
    is_bot = models.BooleanField(
        default=False,
        verbose_name=_("Is Bot")
    )

    # 4. Origin Tracking (Where did we find this user?)
    source_task = models.ForeignKey(
        'crawler.CrawlerTask',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_users',
        verbose_name=_("Source Task")
    )
    source_chat = models.ForeignKey(
        'crawler.TelegramSource',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_users',
        verbose_name=_("Source Chat"),
        help_text=_("The actual group/channel this user was found in.")
    )

    # FIXED: Added the missing crawled_by_account field
    crawled_by_account = models.ForeignKey(
        'telegram_account.TelegramAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='extracted_leads',
        verbose_name=_("Crawled By Account"),
        help_text=_("The specific account that scraped this user. Useful for rotation logic.")
    )

    # 5. Marketing Pipeline Status
    status = models.CharField(
        max_length=20,
        choices=TargetUserStatus.choices,
        default=TargetUserStatus.PENDING,
        db_index=True,
        verbose_name=_("Messaging Status")
    )
    last_messaged_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Messaged At")
    )

    class Meta:
        verbose_name = _("Crawled User")
        verbose_name_plural = _("Crawled Users")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["source_chat"]),
        ]

    def __str__(self):
        name = self.first_name
        if self.last_name:
            name += f" {self.last_name}"
        if self.username:
            return f"{name} (@{self.username})"
        return f"{name} ({self.telegram_id})"

    def mark_as_messaged(self):
        self.status = TargetUserStatus.MESSAGED
        self.last_messaged_at = timezone.now()
        self.save(update_fields=["status", "last_messaged_at", "updated_at"])
