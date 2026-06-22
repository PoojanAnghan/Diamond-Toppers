"""
VDB2 Scrapper API — NinjaAPI Endpoints
=======================================
Provides upload, run, status, and download endpoints for the VDB scraper.
"""

from __future__ import annotations

import os
import sys
import json
import shlex
import logging
import threading
import traceback
from typing import Optional
from uuid import UUID

from django.http import FileResponse, Http404
from django.conf import settings
from django.contrib.auth import authenticate
from ninja import NinjaAPI, Router, File, UploadedFile, Schema
from ninja.security import HttpBearer, SessionAuth

from app.models import ScrapperJob, APIToken, UserGoogleDriveConfig
from app.gdrive_utils import GDriveAuthRequiredError

# ── Ensure vdb2 directory is importable ────────────────────────────────────
VDB2_DIR = os.path.join(settings.BASE_DIR, "vdb2")
if VDB2_DIR not in sys.path:
    sys.path.insert(0, VDB2_DIR)

logger = logging.getLogger(__name__)


# ── Authentication ────────────────────────────────────────────────────────────

class BearerTokenAuth(HttpBearer):
    """
    Authenticates requests via Bearer token.
    Usage: Authorization: Bearer <token>
    """

    def authenticate(self, request, token: str):
        try:
            api_token = APIToken.objects.select_related("user").get(
                token=token,
                is_active=True,
            )
        except APIToken.DoesNotExist:
            return None

        # Attach the user to the request so views can access request.auth
        return api_token.user


# ── NinjaAPI Instance (auth applied globally) ─────────────────────────────
django_auth_no_csrf = SessionAuth(csrf=False)

api = NinjaAPI(
    title="VDB2 Scrapper API",
    version="1.0.0",
    description="Upload .xlsx files, run the VDB diamond scraper, and download enriched results.",
    auth=[BearerTokenAuth(), django_auth_no_csrf],
)

# ── Response Schemas ───────────────────────────────────────────────────────

class JobResponse(Schema):
    id: UUID
    original_filename: str
    status: str
    error_message: str = ""
    created_at: str
    updated_at: str
    google_drive_file_id: str = ""


class ErrorResponse(Schema):
    detail: str


class StatusResponse(Schema):
    id: UUID
    status: str
    error_message: str = ""
    google_drive_file_id: str = ""


class LoginRequest(Schema):
    username: str
    password: str


class LoginResponse(Schema):
    token: str
    username: str


class MessageResponse(Schema):
    detail: str


class GDriveAuthResponse(Schema):
    detail: str
    auth_url: str


class GDriveConfigResponse(Schema):
    is_connected: bool
    folder_id: str


class GDriveConfigRequest(Schema):
    folder_id: str


class CurlConfigRequest(Schema):
    curl_command: str


# ── Constants ────────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {".xlsx"}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

# ── Active Scraper Cancellation Registry ─────────────────────────────────
ACTIVE_SCRAPER_EVENTS: dict[UUID, threading.Event] = {}


# ── Endpoint: Login (no auth required) ───────────────────────────────────

@api.post(
    "/auth/login",
    response={200: LoginResponse, 401: ErrorResponse},
    auth=None,  # No auth required for login
    summary="Login with username and password to get a Bearer token",
)
def login(request, payload: LoginRequest):
    """
    Authenticate with username & password.
    Returns a Bearer token for subsequent API calls.
    """
    user = authenticate(username=payload.username, password=payload.password)
    if user is None or not user.is_active:
        return 401, {"detail": "Invalid credentials."}

    # Create a new token for this session
    token = APIToken.objects.create(user=user, name="login-api")

    return 200, {
        "token": token.token,
        "username": user.username,
    }


# ── Endpoint: Logout ─────────────────────────────────────────────────────

@api.post(
    "/auth/logout",
    response={200: MessageResponse},
    summary="Revoke the current Bearer token",
)
def logout(request):
    """
    Revokes the Bearer token used in this request.
    The token will no longer be valid for future API calls.
    """
    # Extract the token from the Authorization header and deactivate it
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        raw_token = auth_header[7:]
        APIToken.objects.filter(token=raw_token, is_active=True).update(is_active=False)

    return 200, {"detail": "Logged out successfully. Token revoked."}


# ── Helper: Parse cURL Command ──────────────────────────────────────────

def _parse_curl(curl_command: str) -> dict:
    """
    Parses a curl command string using shlex and extracts:
    - api_url
    - authorization
    - cookie
    - user_agent
    """
    try:
        tokens = shlex.split(curl_command)
    except Exception as e:
        raise ValueError(f"Invalid curl command formatting: {e}")

    url = None
    headers = {}
    
    iterator = iter(tokens)
    for token in iterator:
        if token == "curl":
            continue
        elif token in ("-H", "--header"):
            try:
                header_val = next(iterator)
                if ":" in header_val:
                    name, val = header_val.split(":", 1)
                    headers[name.strip().lower()] = val.strip()
            except StopIteration:
                pass
        elif token in ("-b", "--cookie"):
            try:
                cookie_val = next(iterator)
                headers["cookie"] = cookie_val.strip()
            except StopIteration:
                pass
        elif token.startswith("http://") or token.startswith("https://"):
            url = token
        elif token in ("-X", "--request"):
            try:
                next(iterator)  # Skip HTTP method
            except StopIteration:
                pass
        elif token in ("-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode", "-A", "--user-agent", "-e", "--referer"):
            try:
                next(iterator)  # Skip the parameter argument value
            except StopIteration:
                pass

    if not url:
        for token in tokens:
            if token.startswith("http://") or token.startswith("https://"):
                url = token
                break

    if not url:
        raise ValueError("Could not extract VDB API search URL from the curl command.")

    return {
        "api_url": url,
        "authorization": headers.get("authorization"),
        "cookie": headers.get("cookie"),
        "user_agent": headers.get("user-agent"),
    }


# ── Endpoint: Update Session Configuration ───────────────────────────────

@api.post(
    "/auth/session-curl",
    response={200: MessageResponse, 400: ErrorResponse},
    summary="Update VDB API scraper session by pasting a curl command",
)
def update_session_curl(request, payload: CurlConfigRequest):
    """
    Parses the pasted curl command and writes the updated URL, Cookie, Authorization,
    and User-Agent headers to session_config.json.
    """
    try:
        parsed_config = _parse_curl(payload.curl_command)
    except Exception as e:
        return 400, {"detail": str(e)}

    # Validate presence of necessary VDB credentials
    if not parsed_config.get("api_url"):
        return 400, {"detail": "Failed to parse API search URL."}
    if not parsed_config.get("authorization"):
        return 400, {"detail": "Failed to parse Authorization header."}
    if not parsed_config.get("cookie"):
        return 400, {"detail": "Failed to parse Cookie header."}

    # Retrieve local config path dynamically from scraper module
    from scraper import CONFIG_PATH

    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        
        # Keep existing values or merge them
        existing = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                pass

        existing.update({
            "api_url": parsed_config["api_url"],
            "authorization": parsed_config["authorization"],
            "cookie": parsed_config["cookie"],
            "user_agent": parsed_config.get("user_agent") or existing.get("user_agent") or "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
        })

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

    except Exception as e:
        return 400, {"detail": f"Failed to save session configuration: {e}"}

    return 200, {"detail": "Session configuration updated successfully."}


# ── OAuth: Google Drive Authorization ────────────────────────────────────────

@api.get(
    "/auth/gdrive/authorize",
    response={200: GDriveAuthResponse, 400: ErrorResponse},
    summary="Get Google Drive OAuth authorization URL",
)
def gdrive_authorize(request):
    """
    Generates a Google OAuth 2.0 consent URL for the authenticated user.
    The frontend should redirect the user to this URL.
    The `state` parameter encodes the user's Bearer token AND the PKCE
    code_verifier so the callback can complete the token exchange.
    """
    from google_auth_oauthlib.flow import Flow
    from app.gdrive_utils import _load_client_config, SCOPES
    import base64
    import json as _json

    try:
        client_config = _load_client_config()
    except Exception as e:
        return 400, {"detail": f"OAuth configuration error: {e}"}

    # Extract the bearer token from the request to use as state
    auth_header = request.headers.get("Authorization", "")
    bearer_token = ""
    if auth_header.startswith("Bearer "):
        bearer_token = auth_header[7:]

    if not bearer_token:
        return 400, {"detail": "Bearer token required for OAuth state parameter."}

    # Build the OAuth flow
    if not settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON:
        return 400, {"detail": "GOOGLE_OAUTH_CLIENT_SECRET_JSON is not configured."}
    full_client_config = _json.loads(settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON)

    flow = Flow.from_client_config(
        full_client_config,
        scopes=SCOPES,
        redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
    )

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
    )

    # Encode bearer_token + code_verifier into the state parameter
    state_payload = _json.dumps({
        "token": bearer_token,
        "cv": flow.code_verifier,
    })
    state_encoded = base64.urlsafe_b64encode(state_payload.encode()).decode()

    # Append our custom state to the auth URL (replace Google's auto-generated state)
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(auth_url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params['state'] = [state_encoded]
    new_query = urlencode({k: v[0] for k, v in params.items()})
    auth_url = urlunparse(parsed._replace(query=new_query))

    return 200, {"detail": "gdrive_auth_required", "auth_url": auth_url}


@api.get(
    "/auth/gdrive/callback",
    auth=None,  # No auth — this is a browser redirect from Google
    response={200: MessageResponse, 400: ErrorResponse},
    summary="OAuth callback from Google — exchanges code for tokens",
)
def gdrive_callback(request, code: str = "", state: str = "", error: str = ""):
    """
    Google redirects here after the user grants/denies consent.
    Exchanges the authorization code for access + refresh tokens,
    stores them in the database, and redirects to the frontend.
    """
    from django.http import HttpResponseRedirect
    from google_auth_oauthlib.flow import Flow
    import base64
    import json as _json

    frontend_url = settings.FRONTEND_URL

    if error:
        logger.warning("Google Drive OAuth denied: %s", error)
        return HttpResponseRedirect(f"{frontend_url}/?gdrive_error={error}")

    if not code or not state:
        return HttpResponseRedirect(f"{frontend_url}/?gdrive_error=missing_params")

    # Decode the state parameter to extract bearer token and code_verifier
    try:
        state_json = base64.urlsafe_b64decode(state.encode()).decode()
        state_data = _json.loads(state_json)
        bearer_token = state_data["token"]
        code_verifier = state_data.get("cv")
    except Exception:
        logger.error("OAuth callback: failed to decode state parameter")
        return HttpResponseRedirect(f"{frontend_url}/?gdrive_error=invalid_session")

    # Look up the user from the bearer token
    try:
        api_token = APIToken.objects.select_related("user").get(
            token=bearer_token,
            is_active=True,
        )
        user = api_token.user
    except APIToken.DoesNotExist:
        logger.error("OAuth callback: invalid bearer token in state")
        return HttpResponseRedirect(f"{frontend_url}/?gdrive_error=invalid_session")

    # Exchange authorization code for tokens (with the original code_verifier)
    try:
        if not settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON:
            raise ValueError("GOOGLE_OAUTH_CLIENT_SECRET_JSON is not configured.")
        full_client_config = _json.loads(settings.GOOGLE_OAUTH_CLIENT_SECRET_JSON)

        flow = Flow.from_client_config(
            full_client_config,
            scopes=['https://www.googleapis.com/auth/drive'],
            redirect_uri=settings.GOOGLE_OAUTH_REDIRECT_URI,
        )
        # Restore the PKCE code_verifier from the original authorize request
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        creds = flow.credentials
    except Exception as e:
        logger.error("OAuth token exchange failed: %s", e)
        return HttpResponseRedirect(f"{frontend_url}/?gdrive_error=token_exchange_failed")

    # Save tokens to database
    config, _created = UserGoogleDriveConfig.objects.get_or_create(user=user)
    config.token_json = creds.to_json()
    config.save(update_fields=["token_json", "updated_at"])
    logger.info("Saved Google Drive OAuth tokens for user %s", user.username)

    return HttpResponseRedirect(f"{frontend_url}/?gdrive_connected=1")



# ── Endpoint: Google Drive Config ─────────────────────────────────────────

@api.get(
    "/scrapper/gdrive-config",
    response={200: GDriveConfigResponse},
    summary="Get the current user's Google Drive connection status",
)
def get_gdrive_config(request):
    """Returns whether the user has connected Google Drive and their folder ID."""
    try:
        config = UserGoogleDriveConfig.objects.get(user=request.auth)
        return 200, {
            "is_connected": bool(config.token_json),
            "folder_id": config.folder_id,
        }
    except UserGoogleDriveConfig.DoesNotExist:
        return 200, {
            "is_connected": False,
            "folder_id": "",
        }


@api.post(
    "/scrapper/gdrive-config",
    response={200: MessageResponse, 400: ErrorResponse},
    summary="Update Google Drive folder ID for the current user",
)
def update_gdrive_config(request, payload: GDriveConfigRequest):
    """Updates the folder ID where the user's files will be uploaded."""
    config, _created = UserGoogleDriveConfig.objects.get_or_create(user=request.auth)
    config.folder_id = payload.folder_id.strip()
    config.save(update_fields=["folder_id", "updated_at"])
    return 200, {"detail": "Google Drive folder ID updated successfully."}


@api.post(
    "/scrapper/gdrive-disconnect",
    response={200: MessageResponse},
    summary="Disconnect Google Drive for the current user",
)
def disconnect_gdrive(request):
    """Removes the user's stored Google Drive OAuth tokens."""
    UserGoogleDriveConfig.objects.filter(user=request.auth).delete()
    return 200, {"detail": "Google Drive disconnected successfully."}


# ── Helper: Validate uploaded file ─────────────────────────────────────────

def _validate_upload(file: UploadedFile) -> Optional[str]:
    """
    Validate the uploaded file. Returns an error message string, or None if valid.
    """
    # 1. Check extension
    _, ext = os.path.splitext(file.name)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return f"Invalid file type '{ext}'. Only .xlsx files are allowed."

    # 2. Check file size
    if file.size and file.size > MAX_FILE_SIZE_BYTES:
        return f"File too large ({file.size} bytes). Maximum is {MAX_FILE_SIZE_BYTES} bytes (10 MB)."

    # 3. Check filename sanity (no path traversal)
    basename = os.path.basename(file.name)
    if basename != file.name or ".." in file.name:
        return "Invalid filename."

    return None


# ── Helper: Background scraper thread ─────────────────────────────────────

def _run_scraper_thread(job_id: int, user_id: int, dry_run: bool = False):
    """
    Runs the scraper in a background thread. Updates the job status on completion/failure.
    Receives user_id to load the correct user's Google Drive credentials.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    cancel_event = threading.Event()
    job_uuid = None
    try:
        job = ScrapperJob.objects.get(pk=job_id)
        user = User.objects.get(pk=user_id)
        job_uuid = job.job_uuid
        ACTIVE_SCRAPER_EVENTS[job_uuid] = cancel_event

        # Sync the latest file content from Google Drive
        from app.gdrive_utils import download_from_drive, update_drive_file
        logger.info("Downloading file from Google Drive for job %s (ID: %s)...", job.job_uuid, job.google_drive_file_id)
        download_from_drive(user, job.google_drive_file_id, job.file_path)

        job.status = ScrapperJob.STATUS_RUNNING
        job.save(update_fields=["status", "updated_at"])

        # Import scraper here to avoid import issues at module level
        from scraper import run_scraper_for_file

        def on_row_completed():
            # Overwrite & update Google Drive file
            try:
                update_drive_file(user, job.google_drive_file_id, job.file_path)
            except Exception as drive_err:
                logger.warning("Drive sync failed during row callback: %s", drive_err)

        logger.info("Scraper started for job %s (file: %s)", job.job_uuid, job.file_path)
        run_scraper_for_file(
            excel_path=job.file_path,
            dry_run=dry_run,
            cancel_event=cancel_event,
            on_row_completed=on_row_completed
        )

        job.refresh_from_db()
        job.status = ScrapperJob.STATUS_COMPLETED
        job.error_message = ""
        job.save(update_fields=["status", "error_message", "updated_at"])
        logger.info("Scraper completed for job %s", job.job_uuid)

    except Exception as e:
        logger.error("Scraper failed for job %d: %s\n%s", job_id, e, traceback.format_exc())
        try:
            job = ScrapperJob.objects.get(pk=job_id)
            job.status = ScrapperJob.STATUS_FAILED

            # Load the spreadsheet to check for completed rows
            completed_count = 0
            total_count = 0
            try:
                import pandas as pd
                df = pd.read_excel(job.file.path)
                total_count = len(df)
                if "Scrape_Status" in df.columns:
                    completed_count = df["Scrape_Status"].eq("COMPLETED").sum()
            except Exception as read_err:
                logger.error("Failed to read Excel for status count: %s", read_err)

            if cancel_event.is_set() or isinstance(e, InterruptedError):
                job.error_message = f"Cancelled: processed {completed_count}/{total_count} rows. Scraper execution was cancelled by user request."
            else:
                if completed_count > 0:
                    job.error_message = f"Partial failure: processed {completed_count}/{total_count} rows. Error: {str(e)}"[:2000]
                else:
                    job.error_message = f"Scraper failed: {str(e)}"[:2000]

            job.save(update_fields=["status", "error_message", "updated_at"])
        except Exception as update_err:
            logger.error("Failed to update job status for job %d: %s", job_id, update_err)
    finally:
        if job_uuid and job_uuid in ACTIVE_SCRAPER_EVENTS:
            del ACTIVE_SCRAPER_EVENTS[job_uuid]


# ── Endpoint: Upload ──────────────────────────────────────────────────────

@api.post(
    "/scrapper/upload",
    response={200: JobResponse, 400: ErrorResponse, 403: ErrorResponse},
    summary="Upload an .xlsx file for scraping",
)
def upload_file(request, file: UploadedFile = File(...)):
    """
    Upload an .xlsx file. Returns a job object with a UUID that can be used
    to trigger the scraper and download results.
    If the user hasn't authorized Google Drive, returns 403 with an auth URL.
    """
    # Validate
    error = _validate_upload(file)
    if error:
        return 400, {"detail": error}

    # Create job associated with authenticated user
    job = ScrapperJob(original_filename=os.path.basename(file.name), user=request.auth)
    job.save()  # Save first to generate UUID for upload path

    # Save file (upload_to uses job_uuid)
    job.file.save(file.name, file, save=True)

    # Upload to Google Drive (per-user credentials)
    from app.gdrive_utils import upload_to_drive
    try:
        gdrive_id = upload_to_drive(request.auth, job.file.path, job.original_filename)
        job.google_drive_file_id = gdrive_id
        job.save(update_fields=["google_drive_file_id"])
    except GDriveAuthRequiredError:
        # User needs to authorize — clean up the partially created job
        if os.path.exists(job.file.path):
            os.remove(job.file.path)
        job.delete()
        return 403, {"detail": "gdrive_auth_required"}
    except Exception as e:
        logger.error("Failed to upload to Google Drive: %s", e)
        if os.path.exists(job.file.path):
            os.remove(job.file.path)
        job.delete()
        return 400, {"detail": f"Failed to upload to Google Drive: {e}"}

    return 200, {
        "id": job.job_uuid,
        "original_filename": job.original_filename,
        "status": job.status,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "google_drive_file_id": job.google_drive_file_id,
    }


# ── Endpoint: Run Scraper ─────────────────────────────────────────────────

@api.post(
    "/scrapper/run/{job_id}",
    response={200: StatusResponse, 400: ErrorResponse, 404: ErrorResponse},
    summary="Trigger the scraper for a previously uploaded file",
)
def run_scraper(request, job_id: UUID, dry_run: bool = False):
    """
    Start the scraper for the given job. The scraper runs in a background thread.
    Returns immediately with status 'running'.

    Query params:
        dry_run: If true, uses cached data.json instead of real API calls.
    """
    try:
        job = ScrapperJob.objects.get(job_uuid=job_id, user=request.auth)
    except ScrapperJob.DoesNotExist:
        return 404, {"detail": "Job not found."}

    # Prevent re-running a job that's already in progress
    if job.status == ScrapperJob.STATUS_RUNNING:
        return 400, {"detail": "Job is already running."}

    # Reset status if re-running a completed/failed job
    job.status = ScrapperJob.STATUS_PENDING
    job.error_message = ""
    job.save(update_fields=["status", "error_message", "updated_at"])

    # Launch scraper in a background thread (pass user_id for Drive access)
    thread = threading.Thread(
        target=_run_scraper_thread,
        args=(job.pk, request.auth.pk),
        kwargs={"dry_run": dry_run},
        daemon=True,
        name=f"scraper-job-{job.job_uuid}",
    )
    thread.start()

    return 200, {
        "id": job.job_uuid,
        "status": "running",
        "error_message": "",
        "google_drive_file_id": job.google_drive_file_id,
    }


# ── Endpoint: Job Status ──────────────────────────────────────────────────

@api.get(
    "/scrapper/status/{job_id}",
    response={200: StatusResponse, 404: ErrorResponse},
    summary="Check the current status of a scraper job",
)
def get_status(request, job_id: UUID):
    """Returns the current status of the given job."""
    try:
        job = ScrapperJob.objects.get(job_uuid=job_id, user=request.auth)
    except ScrapperJob.DoesNotExist:
        return 404, {"detail": "Job not found."}

    return 200, {
        "id": job.job_uuid,
        "status": job.status,
        "error_message": job.error_message,
        "google_drive_file_id": job.google_drive_file_id,
    }


# ── Endpoint: Download Result ─────────────────────────────────────────────

@api.get(
    "/scrapper/download/{job_id}",
    response={400: ErrorResponse, 404: ErrorResponse},
    summary="Download the enriched .xlsx result file",
)
def download_file(request, job_id: UUID):
    """
    Download the enriched .xlsx file after the scraper has completed.
    Returns a file download response.
    """
    try:
        job = ScrapperJob.objects.get(job_uuid=job_id, user=request.auth)
    except ScrapperJob.DoesNotExist:
        return 404, {"detail": "Job not found."}

    if job.status == ScrapperJob.STATUS_RUNNING:
        return 400, {"detail": "Scraper is still running. Please wait and check status."}

    if job.status == ScrapperJob.STATUS_PENDING:
        return 400, {"detail": "Scraper has not been started yet. Call /run/ first."}

    # Ensure local file is synced with the latest from Google Drive
    from app.gdrive_utils import download_from_drive
    try:
        download_from_drive(request.auth, job.google_drive_file_id, job.file.path)
    except Exception as e:
        logger.warning("Failed to sync file from Google Drive during download request: %s. Falling back to local file.", e)

    # Verify the file exists
    file_path = job.file.path
    if not os.path.isfile(file_path):
        return 404, {"detail": "Result file not found on disk or Google Drive."}

    # Sanitize download filename
    download_name = f"enriched_{job.original_filename}"

    return FileResponse(
        open(file_path, "rb"),
        as_attachment=True,
        filename=download_name,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Endpoint: Flush Data ──────────────────────────────────────────────────

@api.post(
    "/scrapper/flush",
    response={200: MessageResponse, 400: ErrorResponse},
    summary="Flush all scraper jobs, cancel running jobs, and delete uploaded files",
)
def flush_data(request):
    """
    Stops all running jobs and threads, deletes all scraper job records from the database,
    and removes all uploaded Excel files from the disk and Google Drive.
    Excludes User and APIToken records.
    """
    # 1. Cancel all active scraper events
    for event in list(ACTIVE_SCRAPER_EVENTS.values()):
        event.set()
    
    # 2. Wait briefly to allow threads to exit gracefully and release file handles
    import time
    time.sleep(0.1)
    
    # 3. Delete files on Google Drive
    from app.gdrive_utils import delete_from_drive
    for job in ScrapperJob.objects.filter(user=request.auth):
        if job.google_drive_file_id:
            delete_from_drive(request.auth, job.google_drive_file_id)

    # 4. Delete files on disk
    uploads_dir = os.path.join(settings.MEDIA_ROOT, "uploads")
    if os.path.exists(uploads_dir):
        import shutil
        try:
            shutil.rmtree(uploads_dir)
            logger.info("Cleaned up uploads directory: %s", uploads_dir)
        except Exception as e:
            logger.error("Failed to delete uploads directory: %s", e)
            
    # 5. Clear this user's ScrapperJob database rows
    try:
        deleted_count, _ = ScrapperJob.objects.filter(user=request.auth).delete()
        logger.info("Deleted %d ScrapperJob records for user %s", deleted_count, request.auth.username)
    except Exception as e:
        logger.error("Failed to delete ScrapperJob records: %s", e)
        return 400, {"detail": f"Failed to delete scraper jobs from database: {e}"}

    return 200, {"detail": "Successfully cancelled all active threads and flushed all data on server and Google Drive."}
