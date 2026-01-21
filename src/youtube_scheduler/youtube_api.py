from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
DEFAULT_SCOPES = [YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READONLY_SCOPE]


class MissingDependencyError(RuntimeError):
    pass


def _require_google_libs() -> None:
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        import google.auth  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise MissingDependencyError(
            "Missing YouTube dependencies. Install with: pip install 'youtube-scheduler[youtube]'"
        ) from e


@dataclass
class ChannelInfo:
    id: str
    title: str


def load_credentials(*, client_secrets_path: Path, token_path: Path, scopes: list[str]) -> Any:
    """
    Returns google.oauth2.credentials.Credentials.
    """
    _require_google_libs()
    from google.oauth2.credentials import Credentials

    if token_path.exists():
        return Credentials.from_authorized_user_file(str(token_path), scopes=scopes)
    return None


def run_oauth_flow(*, client_secrets_path: Path, token_path: Path, scopes: list[str]) -> Any:
    _require_google_libs()
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=scopes)
    creds = flow.run_local_server(port=0, open_browser=True, authorization_prompt_message="")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def build_youtube_client(creds: Any) -> Any:
    _require_google_libs()
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds)


def get_my_channel_info(youtube: Any) -> ChannelInfo:
    resp = youtube.channels().list(part="snippet", mine=True).execute()
    items = resp.get("items") or []
    if not items:
        raise RuntimeError("No YouTube channel found for this Google account.")
    ch = items[0]
    return ChannelInfo(id=ch["id"], title=ch["snippet"]["title"])


def upload_video(
    *,
    youtube: Any,
    file_path: Path,
    title: str,
    description: str,
    tags: list[str] | None,
    category_id: str | None,
    privacy_status: str,
    publish_at_rfc3339: str | None,
) -> str:
    """
    Uploads a video and returns the YouTube video id.
    For scheduling: privacy_status should be 'private' and publish_at_rfc3339 in the future.
    """
    _require_google_libs()
    from googleapiclient.http import MediaFileUpload

    body: dict[str, Any] = {
        "snippet": {
            "title": title,
            "description": description,
        },
        "status": {
            "privacyStatus": privacy_status,
        },
    }
    if tags:
        body["snippet"]["tags"] = tags
    if category_id:
        body["snippet"]["categoryId"] = category_id
    if publish_at_rfc3339:
        body["status"]["publishAt"] = publish_at_rfc3339

    media = MediaFileUpload(str(file_path), chunksize=-1, resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = req.next_chunk()
        # status may be None for small uploads
    return response["id"]


