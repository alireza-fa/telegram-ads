from django.contrib import admin

from .models import CrawlerTask, CrawlerTaskStatus, CrawledUser, TargetUserStatus


@admin.register(CrawlerTask)
class CrawlerTaskAdmin(admin.ModelAdmin):
    # 1. Display list configuration
    list_display = (
        'target_link',
        'source_type',
        'status',
        'users_crawled',
        'execution_account',
        'created_at'
    )
    list_filter = ('status', 'source_type', 'execution_account', 'created_at')
    search_fields = ('target_link', 'error_message')

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

    # 3. Organize the detail view form (FIXED: Restored original fields for Task)
    fieldsets = (
        ('Execution Strategy', {
            'fields': ('execution_account', 'target_link', 'source_type')
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
        updated_count = queryset.filter(
            status__in=[CrawlerTaskStatus.FAILED, CrawlerTaskStatus.PAUSED]
        ).update(
            status=CrawlerTaskStatus.PENDING,
            attempt_count=0,
            error_message=''
        )
        self.message_user(request, f"{updated_count} tasks successfully restarted and set to PENDING.")

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
    list_filter = ('status', 'is_premium', 'is_bot', 'source_task', 'created_at')
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
        'source_group_link',
        'last_messaged_at',
        'created_at',
        'updated_at'
    )

    # 3. Organize the detail view form (FIXED: help_text changed to description)
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
            'fields': ('source_task', 'source_group_link')
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
