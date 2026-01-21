from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class UploadedVideo:
    file_name: str
    file_sha256: str
    file_size: int
    uploaded_video_id: str
    scheduled_publish_at: str | None = None  # RFC3339
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_json(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "file_sha256": self.file_sha256,
            "file_size": self.file_size,
            "uploaded_video_id": self.uploaded_video_id,
            "scheduled_publish_at": self.scheduled_publish_at,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "UploadedVideo":
        return UploadedVideo(
            file_name=data["file_name"],
            file_sha256=data["file_sha256"],
            file_size=int(data["file_size"]),
            uploaded_video_id=data["uploaded_video_id"],
            scheduled_publish_at=data.get("scheduled_publish_at"),
            created_at=data.get("created_at") or (datetime.utcnow().isoformat() + "Z"),
        )


@dataclass
class Project:
    name: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    # User-provided
    upload_dir: str | None = None
    timezone: str = "UTC"
    videos_per_day: int = 1
    day_start_time: str = "09:00"  # local time HH:MM
    made_for_kids: bool = False

    # Defaults applied to all uploads (can be changed per run)
    default_title: str | None = None
    default_description: str | None = None
    default_tags: list[str] | None = None
    default_category_id: str | None = None

    # OAuth / YouTube info
    client_secrets_path: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None

    # State tracking
    uploaded: list[UploadedVideo] = field(default_factory=list)
    reserved_publish_times: list[str] = field(default_factory=list)  # RFC3339

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "upload_dir": self.upload_dir,
            "timezone": self.timezone,
            "videos_per_day": self.videos_per_day,
            "day_start_time": self.day_start_time,
            "made_for_kids": self.made_for_kids,
            "default_title": self.default_title,
            "default_description": self.default_description,
            "default_tags": self.default_tags,
            "default_category_id": self.default_category_id,
            "client_secrets_path": self.client_secrets_path,
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "uploaded": [u.to_json() for u in self.uploaded],
            "reserved_publish_times": list(self.reserved_publish_times),
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Project":
        p = Project(
            name=data["name"],
            created_at=data.get("created_at") or (datetime.utcnow().isoformat() + "Z"),
            upload_dir=data.get("upload_dir"),
            timezone=data.get("timezone") or "UTC",
            videos_per_day=int(data.get("videos_per_day") or 1),
            day_start_time=data.get("day_start_time") or "09:00",
            made_for_kids=bool(data.get("made_for_kids") or False),
            default_title=data.get("default_title"),
            default_description=data.get("default_description"),
            default_tags=list(data.get("default_tags")) if data.get("default_tags") else None,
            default_category_id=data.get("default_category_id"),
            client_secrets_path=data.get("client_secrets_path"),
            channel_id=data.get("channel_id"),
            channel_title=data.get("channel_title"),
        )
        uploaded = data.get("uploaded") or []
        p.uploaded = [UploadedVideo.from_json(x) for x in uploaded]
        p.reserved_publish_times = list(data.get("reserved_publish_times") or [])
        return p


