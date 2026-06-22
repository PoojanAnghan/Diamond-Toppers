"""
Google Drive Utilities — Per-User OAuth Token Support
=====================================================
All Drive operations use per-user OAuth 2.0 credentials stored in the database
(UserGoogleDriveConfig). Tokens are auto-refreshed when expired.
"""

import os
import json
import logging

from django.conf import settings
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/drive']


class GDriveAuthRequiredError(Exception):
    """Raised when a user has not authorized Google Drive or their token is invalid."""
    pass


def _load_client_config() -> dict:
    """Load the OAuth client config from settings."""
    if not settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON:
        raise ValueError(
            "GOOGLE_OAUTH_CLIENT_SECRET_JSON is not configured. "
            "Please add it to your .env file."
        )
    data = json.loads(settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON)

    # Support both "web" and "installed" client types
    if 'web' in data:
        return data['web']
    elif 'installed' in data:
        return data['installed']
    else:
        raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET_JSON must contain a 'web' or 'installed' key.")


def get_drive_service(user):
    """
    Build and return a Google Drive API v3 service for the given user.
    Loads credentials from the user's UserGoogleDriveConfig record.
    Auto-refreshes expired tokens and saves updated tokens back to DB.

    Raises GDriveAuthRequiredError if:
      - No config exists for the user
      - Token JSON is empty or invalid
      - Token is expired and cannot be refreshed
    """
    from app.models import UserGoogleDriveConfig

    try:
        config = UserGoogleDriveConfig.objects.get(user=user)
    except UserGoogleDriveConfig.DoesNotExist:
        raise GDriveAuthRequiredError("Google Drive is not connected. Please authorize your account.")

    if not config.token_json:
        raise GDriveAuthRequiredError("Google Drive token is missing. Please re-authorize.")

    try:
        token_info = json.loads(config.token_json)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)
    except Exception as e:
        logger.error("Failed to parse stored Google Drive token for user %s: %s", user.username, e)
        raise GDriveAuthRequiredError("Google Drive token is invalid. Please re-authorize.")

    # Auto-refresh expired tokens
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save the refreshed token back to the database
            config.token_json = creds.to_json()
            config.save(update_fields=["token_json", "updated_at"])
            logger.info("Refreshed Google Drive token for user %s", user.username)
        except Exception as e:
            logger.error("Failed to refresh Google Drive token for user %s: %s", user.username, e)
            raise GDriveAuthRequiredError("Google Drive token expired and could not be refreshed. Please re-authorize.")

    if not creds.valid:
        raise GDriveAuthRequiredError("Google Drive token is not valid. Please re-authorize.")

    return build('drive', 'v3', credentials=creds)


def get_folder_id(user) -> str:
    """
    Returns the Drive folder ID configured for this user.
    Falls back to the global GOOGLE_DRIVE_FOLDER_ID setting if the user hasn't set one.
    """
    from app.models import UserGoogleDriveConfig

    try:
        config = UserGoogleDriveConfig.objects.get(user=user)
        if config.folder_id:
            return config.folder_id
    except UserGoogleDriveConfig.DoesNotExist:
        pass

    # Fall back to global setting
    return settings.GOOGLE_DRIVE_FOLDER_ID or ""


def upload_to_drive(user, file_path: str, filename: str) -> str:
    """
    Uploads a local file to Google Drive for the given user.
    Returns the Google Drive File ID.
    """
    service = get_drive_service(user)

    file_metadata = {
        'name': filename,
        'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    }

    folder_id = get_folder_id(user)
    if folder_id:
        file_metadata['parents'] = [folder_id]

    media = MediaFileUpload(
        file_path,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()

    file_id = file.get('id')
    logger.info("User %s: uploaded file to Google Drive. ID: %s", user.username, file_id)
    return file_id


def update_drive_file(user, file_id: str, file_path: str):
    """
    Updates the content of an existing Google Drive file with the local file content.
    """
    service = get_drive_service(user)

    media = MediaFileUpload(
        file_path,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )

    service.files().update(
        fileId=file_id,
        media_body=media
    ).execute()
    logger.info("User %s: updated Google Drive file ID: %s", user.username, file_id)


def download_from_drive(user, file_id: str, dest_path: str):
    """
    Downloads a Google Drive file to the specified destination path.
    """
    service = get_drive_service(user)

    request = service.files().get_media(fileId=file_id)

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

    logger.info("User %s: downloaded Google Drive file ID: %s to %s", user.username, file_id, dest_path)


def delete_from_drive(user, file_id: str):
    """
    Deletes a file from Google Drive.
    """
    try:
        service = get_drive_service(user)
        service.files().delete(fileId=file_id).execute()
        logger.info("User %s: deleted Google Drive file ID: %s", user.username, file_id)
    except GDriveAuthRequiredError:
        logger.warning("User %s: skipping Drive delete for file %s (not authorized)", user.username, file_id)
    except Exception as e:
        logger.error("User %s: failed to delete Google Drive file ID %s: %s", user.username, file_id, e)
