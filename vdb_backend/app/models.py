import uuid
import secrets
from django.db import models
from django.conf import settings


def upload_to_scrapper(instance, filename):
    """Store uploads in a UUID-namespaced directory to prevent path collisions."""
    return f"uploads/{instance.job_uuid}/{filename}"


class ScrapperJob(models.Model):
    """Tracks the lifecycle of a scrapper job: upload → run → download."""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    job_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scrapper_jobs",
        null=True,
        blank=True,
    )
    original_filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=upload_to_scrapper)
    google_drive_file_id = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ScrapperJob {self.job_uuid} ({self.status})"

    @property
    def file_path(self) -> str:
        """Return the absolute filesystem path to the uploaded file."""
        return self.file.path


def _generate_token():
    """Generate a cryptographically secure 40-character hex token."""
    return secrets.token_hex(20)


class APIToken(models.Model):
    """
    Bearer token for API authentication.
    Each token is linked to a Django User and can be revoked via is_active.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    token = models.CharField(
        max_length=40,
        unique=True,
        default=_generate_token,
        db_index=True,
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional label for this token (e.g. 'Postman', 'Frontend')",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        # Show only first 8 chars for safety
        return f"APIToken {self.token[:8]}… ({self.user.username})"


class UserGoogleDriveConfig(models.Model):
    """
    Stores per-user Google Drive OAuth 2.0 tokens and folder configuration.
    Each user authorizes their own Google Drive via the in-browser OAuth flow,
    and their credentials are stored here (never in local files or env vars).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="gdrive_config",
    )
    token_json = models.TextField(
        blank=True,
        default="",
        help_text="Full OAuth 2.0 token JSON (access_token, refresh_token, expiry, etc.)",
    )
    folder_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Google Drive folder ID where this user's files are uploaded.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Google Drive Config"
        verbose_name_plural = "User Google Drive Configs"

    def __str__(self):
        connected = "connected" if self.token_json else "not connected"
        return f"GDriveConfig ({self.user.username}: {connected})"

