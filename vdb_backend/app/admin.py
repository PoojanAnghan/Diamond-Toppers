from django.contrib import admin
from app.models import ScrapperJob, APIToken


@admin.register(ScrapperJob)
class ScrapperJobAdmin(admin.ModelAdmin):
    list_display = ("job_uuid", "original_filename", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("job_uuid", "original_filename")
    readonly_fields = ("job_uuid", "created_at", "updated_at")


@admin.register(APIToken)
class APITokenAdmin(admin.ModelAdmin):
    list_display = ("token_preview", "user", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("user__username", "name")
    readonly_fields = ("token", "created_at")

    def token_preview(self, obj):
        return f"{obj.token[:8]}…"
    token_preview.short_description = "Token"
