import os
import time
import random
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from telethon.sync import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    UserIsBlockedError,
    ChatWriteForbiddenError,
    RPCError,
)

from sender.models import (
    SenderTask,
    SenderTaskStatus,
    MessageType,
    TaskMessage,
    MessageTemplate,
)
from crawler.models import CrawledUser, TargetUserStatus
from telegram_account.models import TelegramAccount

logger = logging.getLogger(__name__)


class SenderLifecycleService:
    """
    Production-oriented sender service for running outbound Telegram campaigns.
    """

    SPAM_RELATED_ERRORS = (PeerFloodError, FloodWaitError)

    USER_LEVEL_FAILURES = (
        UserPrivacyRestrictedError,
        UserIsBlockedError,
        ChatWriteForbiddenError,
    )

    @classmethod
    def get_task_for_processing(cls, task_id: int) -> SenderTask:
        try:
            task = SenderTask.objects.prefetch_related(
                'target_sources',
                'execution_accounts',
                'taskmessage_set__message_template',
            ).get(id=task_id)
        except SenderTask.DoesNotExist:
            raise ValidationError(_("Sender task not found."))

        if task.status not in [SenderTaskStatus.PENDING, SenderTaskStatus.FAILED]:
            raise ValidationError(_("Sender task is not in a processable state."))

        if not task.target_sources.exists():
            raise ValidationError(_("Sender task has no target sources."))

        ordered_messages = task.taskmessage_set.order_by('order')
        if not ordered_messages.exists():
            raise ValidationError(_("Sender task has no messages configured."))

        return task

    def execute_sending(self, task_id: int):
        task = self.get_task_for_processing(task_id)
        task.mark_processing()

        try:
            message_chain = list(
                task.taskmessage_set.select_related('message_template').order_by('order')
            )

            users_queryset = self._get_target_users_queryset(task)
            if not users_queryset.exists():
                task.mark_completed()
                return

            for user in users_queryset.iterator():
                task.refresh_from_db(fields=["status"])
                if task.status == SenderTaskStatus.PAUSED:
                    return

                account = self._pick_available_account(task)
                if not account:
                    task.mark_failed("No ready Telegram account available for sending.")
                    return

                send_result = self._send_message_chain_to_user(
                    user=user,
                    account=account,
                    message_chain=message_chain,
                )

                if send_result == "SPAM_RESTRICTED_ACCOUNT":
                    continue

                if send_result == "USER_FAILED":
                    continue

                if send_result == "SUCCESS":
                    with transaction.atomic():
                        task.users_messaged += 1
                        task.save(update_fields=["users_messaged", "updated_at"])

                self._sleep_with_jitter(task.delay_between_messages)

            if task.status == SenderTaskStatus.PROCESSING:
                task.mark_completed()

        except Exception as exc:
            logger.exception("Unexpected sender execution error for SenderTask ID=%s", task_id)
            task.mark_failed(f"Unexpected Error: {str(exc)}")

    def _get_target_users_queryset(self, task: SenderTask):
        source_ids = task.target_sources.values_list('id', flat=True)

        queryset = CrawledUser.objects.filter(
            status=TargetUserStatus.PENDING,
            source_chat_id__in=source_ids,
            is_bot=False,
        )

        if task.only_premium_users:
            queryset = queryset.filter(is_premium=True)

        return queryset.order_by('created_at')

    def _pick_available_account(self, task: SenderTask):
        selected_accounts = task.execution_accounts.all()

        candidates = selected_accounts if selected_accounts.exists() else TelegramAccount.objects.all()
        candidates = candidates.filter(is_active=True).order_by('last_message_sent_at', 'created_at')

        for account in candidates:
            self._refresh_account_restriction_state(account)

            if account.last_message_sent_at and account.last_message_sent_at.date() < timezone.now().date():
                account.daily_messages_sent = 0
                account.save(update_fields=['daily_messages_sent'])

            if account.is_ready_to_send and account.daily_messages_sent < task.daily_limit_per_account:
                return account

        return None

    @staticmethod
    def _refresh_account_restriction_state(account: TelegramAccount):
        if account.is_restricted and account.restricted_until:
            if timezone.now() >= account.restricted_until:
                account.is_restricted = False
                account.restricted_until = None
                account.save(update_fields=["is_restricted", "restricted_until", "updated_at"])

    def _send_message_chain_to_user(self, user: CrawledUser, account: TelegramAccount,
                                    message_chain: list[TaskMessage]):
        client = TelegramClient(account.session_path, account.api_id, account.api_hash)

        try:
            client.connect()

            if not client.is_user_authorized():
                self._restrict_account(
                    account,
                    reason="Account session is not authorized.",
                    restricted_for=timedelta(days=3650),
                )
                return "SPAM_RESTRICTED_ACCOUNT"

            input_peer = user.username if user.username else user.telegram_id

            try:
                peer_entity = client.get_input_entity(input_peer)
            except ValueError:
                self._mark_user_failed(user)
                return "USER_FAILED"

            for task_message in message_chain:
                template = task_message.message_template
                self._send_single_template(
                    client=client,
                    template=template,
                    peer_entity=peer_entity,
                )

                intra_chain_delay = random.uniform(1.0, 2.5)
                time.sleep(intra_chain_delay)

            self._mark_successful_send(user, account)
            return "SUCCESS"

        except self.SPAM_RELATED_ERRORS as exc:
            self._handle_spam_restriction(account, exc)
            return "SPAM_RESTRICTED_ACCOUNT"

        except self.USER_LEVEL_FAILURES:
            self._mark_user_failed(user)
            return "USER_FAILED"

        except RPCError as exc:
            error_text = str(exc).lower()

            if any(keyword in error_text for keyword in ["flood", "peerflood", "spam"]):
                self._handle_spam_restriction(account, exc)
                return "SPAM_RESTRICTED_ACCOUNT"

            if any(keyword in error_text for keyword in ["privacy", "blocked", "forbidden"]):
                self._mark_user_failed(user)
                return "USER_FAILED"

            self._mark_user_failed(user)
            return "USER_FAILED"

        except Exception:
            self._mark_user_failed(user)
            return "USER_FAILED"

        finally:
            client.disconnect()

    def _send_single_template(self, client: TelegramClient, template: MessageTemplate, peer_entity):
        if template.message_type == MessageType.TEXT:
            client.send_message(
                entity=peer_entity,
                message=template.text_content,
            )
            return

        if template.message_type == MessageType.VOICE:
            if not template.telegram_file_id:
                self._cache_voice_in_saved_messages(client, template)

            cached_msg_id = int(template.telegram_file_id)
            cached_msg = client.get_messages('me', ids=cached_msg_id)

            if not cached_msg or not cached_msg.media:
                self._cache_voice_in_saved_messages(client, template)
                cached_msg_id = int(template.telegram_file_id)
                cached_msg = client.get_messages('me', ids=cached_msg_id)

            client.send_file(
                entity=peer_entity,
                file=cached_msg.media,
                voice_note=True,
                caption=template.text_content or None,
            )
            return

        raise ValidationError(_("Unsupported message type."))

    @staticmethod
    def _cache_voice_in_saved_messages(client: TelegramClient, template: MessageTemplate):
        if not template.voice_file:
            raise ValidationError(_("Voice template has no uploaded file."))

        upload_path = template.voice_file.path
        if not os.path.exists(upload_path):
            raise ValidationError(_("Voice file does not exist on disk."))

        msg = client.send_file('me', upload_path, voice_note=True)

        template.telegram_file_id = str(msg.id)
        template.save(update_fields=["telegram_file_id", "updated_at"])

    @transaction.atomic
    def _mark_successful_send(self, user: CrawledUser, account: TelegramAccount):
        user.status = TargetUserStatus.MESSAGED
        user.last_messaged_at = timezone.now()
        user.save(update_fields=["status", "last_messaged_at", "updated_at"])

        account.daily_messages_sent += 1
        account.last_message_sent_at = timezone.now()
        account.save(update_fields=["daily_messages_sent", "last_message_sent_at", "updated_at"])

    @transaction.atomic
    def _mark_user_failed(self, user: CrawledUser):
        user.status = TargetUserStatus.FAILED
        user.save(update_fields=["status", "updated_at"])

    def _handle_spam_restriction(self, account: TelegramAccount, exc: Exception):
        if isinstance(exc, FloodWaitError):
            restricted_for = timedelta(seconds=exc.seconds)
            reason = f"FloodWaitError: Must wait {exc.seconds} seconds."
        else:
            restricted_for = timedelta(hours=24)
            reason = f"Spam/Restriction detected: {str(exc)}"

        self._restrict_account(account, reason=reason, restricted_for=restricted_for)

    @transaction.atomic
    def _restrict_account(self, account: TelegramAccount, reason: str, restricted_for: timedelta):
        account.is_restricted = True
        account.restricted_until = timezone.now() + restricted_for
        account.save(update_fields=["is_restricted", "restricted_until", "updated_at"])
        logger.warning("TelegramAccount %s restricted. Reason: %s", account.phone_number, reason)

    def _sleep_with_jitter(self, base_delay: int):
        delay = random.uniform(base_delay, base_delay + max(5, int(base_delay * 0.35)))
        time.sleep(delay)
