from django.contrib import admin
from django.db import transaction

from .models import (
    MessageTemplate,
    SenderTask,
    TaskMessage,
    SenderTaskStatus
)


# from .tasks import process_sender_task


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ('title', 'message_type', 'has_voice_file', 'created_at')
    list_filter = ('message_type', 'created_at')
    search_fields = ('title', 'text_content')

    readonly_fields = ('telegram_file_id', 'created_at', 'updated_at')

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'message_type')
        }),
        ('Content', {
            'fields': ('text_content', 'voice_file', 'telegram_id_info'),
            'description': 'For VOICE type, upload an .ogg file. Telegram File ID will be generated automatically.'
        }),
        ('System Info', {
            'fields': ('telegram_file_id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def has_voice_file(self, obj):
        return bool(obj.voice_file)

    has_voice_file.boolean = True
    has_voice_file.short_description = "Has Voice"

    def telegram_id_info(self, obj):
        if obj.telegram_file_id:
            return f"Cached ID: {obj.telegram_file_id[:15]}..."
        return "No File ID cached yet."

    telegram_id_info.short_description = "Cache Status"


class TaskMessageInline(admin.TabularInline):
    """
    Allows adding and ordering messages directly inside the SenderTask admin page.
    """
    model = TaskMessage
    extra = 1
    ordering = ('order',)
    autocomplete_fields = ['message_template']


@admin.register(SenderTask)
class SenderTaskAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'status',
        'users_messaged',
        'daily_limit_per_account',
        'created_at'
    )
    list_filter = ('status', 'only_premium_users', 'created_at')
    search_fields = ('title',)

    filter_horizontal = ('execution_accounts', 'target_sources')

    inlines = [TaskMessageInline]

    readonly_fields = (
        'users_messaged',
        'created_at',
        'updated_at'
    )

    fieldsets = (
        ('Campaign Info', {
            'fields': ('title', 'status')
        }),
        ('Targeting & Filters', {
            'fields': ('target_sources', 'only_premium_users')
        }),
        ('Execution Rotation', {
            'fields': ('execution_accounts',),
            'description': 'Select multiple accounts to rotate them and prevent bans.'
        }),
        ('Anti-Spam Configuration', {
            'fields': ('daily_limit_per_account', 'delay_between_messages')
        }),
        ('Progress (Read-Only)', {
            'fields': ('users_messaged',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['restart_failed_tasks', 'pause_active_tasks']

    @admin.action(description='Restart selected failed/paused campaigns')
    def restart_failed_tasks(self, request, queryset):
        tasks_to_restart = queryset.filter(
            status__in=[SenderTaskStatus.FAILED, SenderTaskStatus.PAUSED]
        )

        task_ids = list(tasks_to_restart.values_list('id', flat=True))

        updated_count = tasks_to_restart.update(
            status=SenderTaskStatus.PENDING,
        )

        # TODO: Uncomment after creating sender/tasks.py
        # for task_id in task_ids:
        #     transaction.on_commit(lambda tid=task_id: process_sender_task.delay(tid))

        self.message_user(request, f"{updated_count} campaigns successfully restarted and sent to Celery.")

    @admin.action(description='Pause selected pending/processing campaigns')
    def pause_active_tasks(self, request, queryset):
        updated_count = queryset.filter(
            status__in=[SenderTaskStatus.PENDING, SenderTaskStatus.PROCESSING]
        ).update(
            status=SenderTaskStatus.PAUSED
        )
        self.message_user(request, f"{updated_count} campaigns successfully paused.")

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        super().save_model(request, obj, form, change)

        # TODO: Uncomment after creating sender/tasks.py
        # if is_new and obj.status == SenderTaskStatus.PENDING:
        #     transaction.on_commit(lambda: process_sender_task.delay(obj.id))
