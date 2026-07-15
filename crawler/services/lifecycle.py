import time
import random

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from telethon.sync import TelegramClient
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.errors import UserAlreadyParticipantError, InviteHashExpiredError, FloodWaitError

from crawler.models import CrawlerTask, CrawlerTaskStatus, CrawledUser, TargetUserStatus
from telegram_account.models import TelegramAccount


class CrawlerLifecycleService:

    @classmethod
    def get_task_for_processing(cls, task_id: int) -> CrawlerTask:
        """
        Fetches the task and validates if it can be processed.
        Assigns an execution account if not already assigned.
        """
        try:
            # Optimize by selecting related source to avoid N+1 query issues
            task = CrawlerTask.objects.select_related('source').get(id=task_id)
        except CrawlerTask.DoesNotExist:
            raise ValidationError(_("Crawler task not found."))

        if task.status not in [CrawlerTaskStatus.PENDING, CrawlerTaskStatus.FAILED]:
            raise ValidationError(_("Task is not in a state to be processed."))

        # Assign an available account if needed
        if not task.execution_account:
            available_account = TelegramAccount.objects.filter(
                is_active=True,
                is_restricted=False
            ).first()

            if not available_account:
                raise ValidationError(_("No active and unrestricted Telegram accounts available."))

            task.execution_account = available_account
            task.save(update_fields=['execution_account'])

        return task

    def execute_crawling(self, task_id: int):
        """
        The main worker loop for connecting to Telegram and fetching data.
        DO NOT wrap this entire function in transaction.atomic!
        """
        task = self.get_task_for_processing(task_id)
        account = task.execution_account

        task.mark_processing()

        # Initialize Telethon Client (Sync mode for Celery tasks)
        client = TelegramClient(account.session_path, account.api_id, account.api_hash)

        try:
            client.connect()
            if not client.is_user_authorized():
                task.mark_failed("Account session is not authorized.")
                return

            # 1. Resolve Target (Join if necessary) using the new Source relation
            target_entity = self._resolve_and_join_target(client, task)

            # 2. Begin Crawling Loop
            # Offset ID is crucial for resuming paused/failed tasks
            offset_id = task.last_message_id if task.last_message_id else 0

            # Using iter_messages to fetch history
            messages = client.iter_messages(
                target_entity,
                offset_id=offset_id,
                reverse=False  # Start from older to newer
            )

            for message in messages:
                # Check limits
                if task.users_crawled >= task.target_user_count:
                    task.mark_completed()
                    break

                if task.messages_scanned >= task.message_scan_limit:
                    task.mark_completed()
                    break

                # Process the message sender
                if message.sender_id:
                    self._process_and_save_user(client, message.sender_id, task, account)

                # Update progress incrementally (every 100 messages to avoid DB bottleneck)
                if task.messages_scanned % 100 == 0:
                    with transaction.atomic():
                        task.last_message_id = message.id
                        task.save(update_fields=['last_message_id', 'messages_scanned'])

                # Human-like delay logic (e.g., pause briefly every 50 messages)
                if task.messages_scanned % 50 == 0:
                    delay = random.uniform(1.5, 4.0)
                    time.sleep(delay)

                task.messages_scanned += 1

            # Finalize if loop finished normally
            if task.status == CrawlerTaskStatus.PROCESSING:
                task.mark_completed()

        except FloodWaitError as e:
            # Handle rate limiting gracefully
            task.mark_failed(f"FloodWaitError: Must wait {e.seconds} seconds.")

        except Exception as e:
            task.mark_failed(f"Unexpected Error: {str(e)}")

        finally:
            if task.source:
                task.source.last_crawled_at = timezone.now()
                task.source.save(update_fields=['last_crawled_at'])

            client.disconnect()

    def _resolve_and_join_target(self, client: TelegramClient, task: CrawlerTask):
        """
        Helper method to figure out the entity and join if it's a new link.
        Accesses target details via the related TelegramSource model.
        """
        # FIXED: Accessing telegram_id via the source relation
        if task.source.telegram_id:
            return client.get_entity(task.source.telegram_id)

        # FIXED: Accessing link via the source relation
        target = task.source.link

        try:
            # Handle private invite links
            if '/+' in target or 'joinchat' in target:
                hash_part = target.split('/')[-1].replace('+', '')
                try:
                    client(ImportChatInviteRequest(hash_part))
                except UserAlreadyParticipantError:
                    pass
                except InviteHashExpiredError:
                    raise ValueError("The invite link is expired.")

                return client.get_entity(target)

            # Handle public usernames/links
            else:
                entity = client.get_entity(target)
                try:
                    client(JoinChannelRequest(entity))
                except UserAlreadyParticipantError:
                    pass
                return entity

        except Exception as e:
            raise ValueError(f"Failed to resolve or join target: {str(e)}")

    @transaction.atomic
    def _process_and_save_user(self, client: TelegramClient, sender_id: int, task: CrawlerTask,
                               account: TelegramAccount):
        """
        Fetches user details and saves to DB atomically.
        """
        # Skip if already exists in DB
        if CrawledUser.objects.filter(telegram_id=sender_id).exists():
            return

        try:
            user_entity = client.get_entity(sender_id)

            if user_entity.bot:
                return

            CrawledUser.objects.create(
                telegram_id=user_entity.id,
                username=user_entity.username,
                first_name=user_entity.first_name or "",
                last_name=user_entity.last_name,
                phone_number=user_entity.phone,
                is_premium=getattr(user_entity, 'premium', False),
                is_bot=user_entity.bot,
                source_task=task,
                source_chat=task.source,
                crawled_by_account=account,
                status=TargetUserStatus.PENDING
            )

            task.users_crawled += 1
            task.save(update_fields=['users_crawled'])

        except ValueError:
            pass
        except Exception:
            pass
