from django.contrib import admin
from django.db import transaction

from .models import (
    CrawlerTask,
    CrawlerTaskStatus,
    CrawledUser,
    TargetUserStatus,
    TelegramSource
)
from .tasks import process_crawler_task


@admin.register(TelegramSource)
class TelegramSourceAdmin(admin.ModelAdmin):
    # 1. Display list configuration
    list_display = (
        'title',
        'link',
        'chat_type',
        'is_active',
        'last_crawled_at',
        'created_at'
    )
    list_filter = ('chat_type', 'is_active', 'created_at')
    search_fields = ('title', 'link', 'telegram_id')

    # 2. Organize the detail view form
    readonly_fields = ('created_at', 'updated_at', 'last_crawled_at')
    fieldsets = (
        ('Source Information', {
            'fields': ('title', 'link', 'telegram_id', 'chat_type')
        }),
        ('Status', {
            'fields': ('is_active', 'last_crawled_at'),
            'description': 'Disable "Is Active" to pause operations for this source.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CrawlerTask)
class CrawlerTaskAdmin(admin.ModelAdmin):
    # 1. Display list configuration
    list_display = (
        'source',
        'crawl_method',
        'status',
        'users_crawled',
        'execution_account',
        'created_at'
    )
    list_filter = ('status', 'crawl_method', 'execution_account', 'created_at')
    search_fields = ('source__title', 'source__link', 'error_message')

    # 2. Prevent manual modification of progress tracking fields
    readonly_fields = (
        'users_crawled',
        'messages_scanned',
        'last_message_id',
        'attempt_count',
        'error_message',
        'started_at',
        'completed_at',
        'created_at',
        'updated_at'
    )

    # 3. Organize the detail view form
    fieldsets = (
        ('Execution Strategy', {
            'fields': ('execution_account', 'source', 'crawl_method')
        }),
        ('Limits & Filters', {
            'fields': ('target_user_count', 'message_scan_limit', 'include_admins')
        }),
        ('Status & Progress (Read-Only)', {
            'fields': (
                'status',
                'users_crawled',
                'messages_scanned',
                'last_message_id',
                'error_message',
                'attempt_count',
                'max_attempts'
            )
        }),
        ('Timestamps', {
            'fields': ('started_at', 'completed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # 4. Custom Admin Actions
    actions = ['restart_failed_tasks', 'pause_active_tasks']

    @admin.action(description='Restart selected failed/paused tasks')
    def restart_failed_tasks(self, request, queryset):
        tasks_to_restart = queryset.filter(
            status__in=[CrawlerTaskStatus.FAILED, CrawlerTaskStatus.PAUSED]
        )

        task_ids = list(tasks_to_restart.values_list('id', flat=True))

        updated_count = tasks_to_restart.update(
            status=CrawlerTaskStatus.PENDING,
            attempt_count=0,
            error_message=''
        )

        for task_id in task_ids:
            transaction.on_commit(lambda tid=task_id: process_crawler_task.delay(tid))

        self.message_user(request, f"{updated_count} tasks successfully restarted and sent to Celery.")

    @admin.action(description='Pause selected pending/processing tasks')
    def pause_active_tasks(self, request, queryset):
        updated_count = queryset.filter(
            status__in=[CrawlerTaskStatus.PENDING, CrawlerTaskStatus.PROCESSING]
        ).update(
            status=CrawlerTaskStatus.PAUSED
        )
        self.message_user(request, f"{updated_count} tasks successfully paused.")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields + ('execution_account',)
        return self.readonly_fields

    # 5. Overriding save_model to trigger task on creation
    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None

        super().save_model(request, obj, form, change)

        if is_new and obj.status == CrawlerTaskStatus.PENDING:
            transaction.on_commit(lambda: process_crawler_task.delay(obj.id))


@admin.register(CrawledUser)
class CrawledUserAdmin(admin.ModelAdmin):
    # 1. Display list configuration
    list_display = (
        'telegram_id',
        'username',
        'first_name',
        'status',
        'is_premium',
        'source_task',
        'created_at'
    )
    list_filter = ('status', 'is_premium', 'is_bot', 'source_task', 'crawled_by_account', 'created_at')
    search_fields = ('telegram_id', 'username', 'first_name', 'last_name', 'phone_number')

    # 2. Prevent manual modification of scraped data
    readonly_fields = (
        'telegram_id',
        'username',
        'first_name',
        'last_name',
        'phone_number',
        'is_premium',
        'is_bot',
        'source_task',
        'source_chat',
        'crawled_by_account',
        'last_messaged_at',
        'created_at',
        'updated_at'
    )

    # 3. Organize the detail view form
    fieldsets = (
        ('Telegram Profile (Read-Only)', {
            'fields': (
                'telegram_id',
                'username',
                'first_name',
                'last_name',
                'phone_number',
                'is_premium',
                'is_bot'
            )
        }),
        ('Origin Tracking (Read-Only)', {
            'fields': ('source_task', 'source_chat', 'crawled_by_account')
        }),
        ('Marketing Pipeline', {
            'fields': ('status', 'last_messaged_at'),
            'description': 'Change status manually if needed.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    # 4. Custom Admin Actions for Pipeline Management
    actions = ['reset_to_pending', 'mark_as_failed']

    @admin.action(description='Reset selected users to PENDING (Ready to message)')
    def reset_to_pending(self, request, queryset):
        updated_count = queryset.update(status=TargetUserStatus.PENDING)
        self.message_user(request, f"{updated_count} users successfully reset to PENDING.")

    @admin.action(description='Mark selected users as FAILED (Exclude from messaging)')
    def mark_as_failed(self, request, queryset):
        updated_count = queryset.update(status=TargetUserStatus.FAILED)
        self.message_user(request, f"{updated_count} users marked as FAILED and excluded.")

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return self.readonly_fields
        return 'last_messaged_at', 'created_at', 'updated_at'
