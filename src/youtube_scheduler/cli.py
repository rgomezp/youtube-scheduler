from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import click
import typer
import time
from rich.console import Console
from rich.table import Table

from .models import UploadedVideo
from .paths import app_home, ensure_dirs, projects_dir
from .storage import create_project, delete_project, list_projects, load_project, save_project
from .utils import generate_schedule_slots, sha256_file
from .youtube_api import (
    DEFAULT_SCOPES,
    MissingDependencyError,
    build_youtube_client,
    get_my_channel_info,
    run_oauth_flow,
    upload_video,
)


app = typer.Typer(help="Upload + schedule YouTube videos with per-project isolation.")
projects_app = typer.Typer(help="Manage projects.")
app.add_typer(projects_app, name="projects")

console = Console()

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _project_token_path(project_name: str) -> Path:
    ensure_dirs()
    return projects_dir() / f"{project_name}.token.json"


def _require_project(name: str):
    try:
        return load_project(name)
    except FileNotFoundError:
        raise typer.BadParameter(f"Project not found: {name}. Run: yt-scheduler init")


@app.command()
def where():
    """Show where youtube-scheduler stores its data."""
    console.print(str(app_home()))


@projects_app.command("list")
def projects_list():
    """List saved projects."""
    names = list_projects()
    if not names:
        console.print("No projects yet. Run: yt-scheduler init")
        raise typer.Exit(code=0)
    table = Table(title="Projects")
    table.add_column("Name")
    for n in names:
        table.add_row(n)
    console.print(table)


@projects_app.command("delete")
def projects_delete(name: str = typer.Argument(..., help="Project name to delete")):
    """Delete a project JSON (does not delete uploaded videos)."""
    delete_project(name)
    console.print(f"Deleted project: {name}")


@app.command()
def init(
    name: str = typer.Option("", prompt="Project name (e.g. my-channel-2026)"),
):
    """
    Create a new project and walk through setup.
    """
    ensure_dirs()
    try:
        project = create_project(name)
        console.print(f"\nCreated project [bold]{project.name}[/bold]")
        console.print(f"Stored at: {projects_dir() / (project.name + '.json')}\n")
    except FileExistsError:
        project = load_project(name)
        console.print(f"\nLoaded existing project [bold]{project.name}[/bold] (resuming setup)")
        console.print(f"Stored at: {projects_dir() / (project.name + '.json')}\n")

    console.print("[bold]Next: Google setup walkthrough[/bold]")
    console.print(
        "\n1) In Google Cloud Console, create/select a project\n"
        "2) Enable: YouTube Data API v3\n"
        "3) Configure OAuth consent screen (External)\n"
        "   - User type: External (most users)\n"
        "   - App name + user support email + developer contact email (required)\n"
        "   - Add scopes:\n"
        f"     - {DEFAULT_SCOPES[0]}\n"
        f"     - {DEFAULT_SCOPES[1]}\n"
        "   - While in Testing, add developer-approved testers:\n"
        "     OAuth consent screen → Audience → Test users → Add users → (enter Gmail addresses)\n"
        "4) Create OAuth Client ID (type: \"Desktop app\")\n"
        "5) Download the JSON client secrets file\n"
    )

    # Client secrets (skip re-prompting if already set unless user wants to change it)
    if project.client_secrets_path:
        console.print(f"\nClient secrets: [bold]{project.client_secrets_path}[/bold]")
        console.print("[dim]Tip: press Enter to accept the default shown in [brackets].[/dim]")
        change_secrets = typer.confirm("Change client secrets path?", default=False)
        if change_secrets:
            secrets = typer.prompt("New path to client secrets JSON").strip()
        else:
            secrets = ""
    else:
        secrets = typer.prompt(
            "\nPath to your downloaded client secrets JSON (or leave blank to set later)",
            default="",
            show_default=False,
        ).strip()
    if secrets:
        secrets_path = Path(secrets).expanduser().resolve()
        if not secrets_path.exists():
            raise typer.BadParameter(f"File not found: {secrets_path}")
        project.client_secrets_path = str(secrets_path)

    # Basic scheduling prefs
    if project.upload_dir:
        console.print(f"\nUpload directory: [bold]{project.upload_dir}[/bold]")
        console.print("[dim]Tip: press Enter to accept the default shown in [brackets].[/dim]")
        change_dir = typer.confirm("Change upload directory?", default=False)
        if change_dir:
            upload_dir = typer.prompt(
                "Directory you will upload videos from (can set later)",
                default="",
                show_default=False,
            ).strip()
        else:
            upload_dir = ""
    else:
        upload_dir = typer.prompt(
            "Directory you will upload videos from (can set later)",
            default="",
            show_default=False,
        ).strip()
    if upload_dir:
        p = Path(upload_dir).expanduser()
        if p.exists():
            p = p.resolve()
            if not p.is_dir():
                console.print(f"[yellow]Warning:[/yellow] Not a directory: {p} (skipping; you can set later)")
            else:
                project.upload_dir = str(p)
        else:
            create = typer.confirm(f"Directory does not exist: {p}\nCreate it now?", default=True)
            if create:
                p.mkdir(parents=True, exist_ok=True)
                project.upload_dir = str(p.resolve())
            else:
                console.print("OK — skipping upload directory for now. You can set it later.")

    # These are safe to re-ask with defaults; they also make it clear what the project currently uses.
    console.print("\n[dim]Tip: press Enter to keep the current value shown in [brackets].[/dim]")
    project.timezone = typer.prompt("Your timezone (IANA, e.g. America/New_York)", default=project.timezone)
    project.videos_per_day = int(typer.prompt("How many videos per day?", default=str(project.videos_per_day)))
    project.day_start_time = typer.prompt("What time should the day's schedule start? (HH:MM)", default=project.day_start_time)

    save_project(project)
    console.print("\nSaved project settings.")

    if project.client_secrets_path:
        do_auth = typer.confirm("Authenticate now (recommended)?", default=True)
        if do_auth:
            auth(project.name)


@app.command()
def auth(
    project: str = typer.Argument(..., help="Project name"),
):
    """Run OAuth flow and save a refresh token for this project."""
    p = _require_project(project)
    if not p.client_secrets_path:
        raise typer.BadParameter("Project missing client_secrets_path. Run: yt-scheduler init (or edit the project JSON).")
    secrets_path = Path(p.client_secrets_path).expanduser().resolve()
    token_path = _project_token_path(p.name)

    try:
        creds = run_oauth_flow(client_secrets_path=secrets_path, token_path=token_path, scopes=DEFAULT_SCOPES)
        yt = build_youtube_client(creds)
        ch = get_my_channel_info(yt)
        p.channel_id = ch.id
        p.channel_title = ch.title
        save_project(p)
        console.print(f"Authenticated. Channel: [bold]{ch.title}[/bold] ({ch.id})")
        console.print(f"Token saved at: {token_path}")
    except MissingDependencyError as e:
        console.print(str(e))
        raise typer.Exit(code=2)


def _video_already_uploaded(project, sha256: str, size: int) -> bool:
    for u in project.uploaded:
        if u.file_sha256 == sha256 and u.file_size == size:
            return True
    return False


@app.command()
def cleanup(
    project: str = typer.Argument(..., help="Project name"),
    directory: Optional[str] = typer.Option(None, help="Directory to clean (overrides project setting)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview deletions without deleting"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Delete local video files that have already been successfully uploaded for this project.

    Safety checks:
    - Only deletes files whose (name, size, sha256) match a recorded uploaded entry.
    - Defaults to dry-run.
    """
    p = _require_project(project)
    upload_dir = Path(directory).expanduser().resolve() if directory else (Path(p.upload_dir).expanduser().resolve() if p.upload_dir else None)
    if upload_dir is None:
        raise typer.BadParameter("No upload directory set. Provide --directory or set upload_dir in the project.")
    if not upload_dir.exists() or not upload_dir.is_dir():
        raise typer.BadParameter(f"Not a directory: {upload_dir}")

    if not p.uploaded:
        console.print("No uploaded videos recorded for this project yet. Nothing to clean.")
        raise typer.Exit(code=0)

    # Build quick lookup: filename -> list of (sha,size)
    uploaded_by_name: dict[str, list[tuple[str, int]]] = {}
    for u in p.uploaded:
        uploaded_by_name.setdefault(u.file_name, []).append((u.file_sha256, int(u.file_size)))

    # Candidate files: only those with names we recognize
    candidates = []
    for file_name in sorted(uploaded_by_name.keys()):
        fp = upload_dir / file_name
        if fp.exists() and fp.is_file():
            candidates.append(fp)

    if not candidates:
        console.print("No matching uploaded files found in the directory. Nothing to clean.")
        raise typer.Exit(code=0)

    to_delete: list[Path] = []
    total_bytes = 0
    console.print(f"Checking {len(candidates)} candidate files for safe deletion...")
    for fp in candidates:
        size = fp.stat().st_size
        sha = sha256_file(fp)
        allowed = uploaded_by_name.get(fp.name) or []
        if (sha, size) in allowed:
            to_delete.append(fp)
            total_bytes += size

    if not to_delete:
        console.print("No files matched uploaded records by hash+size. Nothing to delete.")
        raise typer.Exit(code=0)

    table = Table(title="Files eligible for deletion (already uploaded)")
    table.add_column("File")
    table.add_column("Size (MB)", justify="right")
    for fp in to_delete:
        table.add_row(fp.name, f"{fp.stat().st_size / (1024*1024):.2f}")
    console.print(table)
    console.print(f"Total space to free: [bold]{total_bytes / (1024*1024):.2f} MB[/bold]")

    if dry_run:
        console.print("\nDry-run enabled (no files deleted). Re-run with --no-dry-run to delete.")
        raise typer.Exit(code=0)

    if not yes:
        ok = typer.confirm("Delete these files now?", default=False)
        if not ok:
            console.print("Cancelled.")
            raise typer.Exit(code=0)

    deleted = 0
    for fp in to_delete:
        try:
            fp.unlink()
            deleted += 1
        except Exception as e:
            console.print(f"[yellow]Warning:[/yellow] Failed to delete {fp}: {e}")

    console.print(f"\nDeleted {deleted}/{len(to_delete)} files.")


@app.command()
def upload(
    project: str = typer.Argument(..., help="Project name"),
    directory: Optional[str] = typer.Option(None, help="Directory containing videos (overrides project setting)"),
    dry_run: bool = typer.Option(False, help="Plan schedule without uploading"),
    throttle_seconds: float = typer.Option(1.0, help="Delay between video uploads to reduce rate-limit risk"),
):
    """
    Upload and schedule any new videos found in the directory.
    Skips anything previously uploaded in this project.
    """
    p = _require_project(project)
    upload_dir = Path(directory).expanduser().resolve() if directory else (Path(p.upload_dir).expanduser().resolve() if p.upload_dir else None)
    if upload_dir is None:
        raise typer.BadParameter("No upload directory set. Provide --directory or set upload_dir in the project.")
    if not upload_dir.exists() or not upload_dir.is_dir():
        raise typer.BadParameter(f"Not a directory: {upload_dir}")

    token_path = _project_token_path(p.name)
    if not token_path.exists() and not dry_run:
        raise typer.BadParameter("Not authenticated for this project. Run: yt-scheduler auth <project>")

    # Scan for video files (simple filter)
    exts = {".mp4", ".mov", ".mkv", ".webm"}
    files = sorted([f for f in upload_dir.iterdir() if f.is_file() and f.suffix.lower() in exts])
    if not files:
        console.print(f"No video files found in {upload_dir} (expected one of: {', '.join(sorted(exts))})")
        raise typer.Exit(code=0)

    # Identify new videos
    new_files: list[Path] = []
    hashes: dict[Path, tuple[str, int]] = {}
    console.print(f"Found {len(files)} files. Checking which are new for project [bold]{p.name}[/bold]...")
    for f in files:
        size = f.stat().st_size
        sha = sha256_file(f)
        hashes[f] = (sha, size)
        if not _video_already_uploaded(p, sha, size):
            new_files.append(f)

    if not new_files:
        console.print("Nothing new to upload. You're all caught up.")
        raise typer.Exit(code=0)

    console.print(f"New videos to upload: [bold]{len(new_files)}[/bold]")

    # Ask scheduling preferences (allow per-run override)
    console.print("\n[dim]Tip: press Enter to keep the current value shown in [brackets].[/dim]")
    videos_per_day = int(typer.prompt("How many videos per day?", default=str(p.videos_per_day)))
    timezone = typer.prompt("Timezone (IANA)", default=p.timezone)
    day_start_time = typer.prompt("Day start time (HH:MM)", default=p.day_start_time)

    # Start schedule: today (from now) or a future date
    start_mode = typer.prompt(
        "When should scheduling start? (today/future)",
        type=click.Choice(["today", "future"], case_sensitive=False),
        default="today",
    ).lower()
    if start_mode == "future":
        if ZoneInfo is None:
            raise typer.BadParameter("Future-date scheduling requires Python 3.9+ (zoneinfo).")
        date_str = typer.prompt("Enter start date (YYYY-MM-DD)")
        try:
            dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        except ValueError:
            raise typer.BadParameter("Invalid date format. Expected YYYY-MM-DD.")
        start_dt = datetime(dt.year, dt.month, dt.day, 0, 0, tzinfo=ZoneInfo(timezone))
    else:
        start_dt = datetime.now().astimezone()

    reserved = set(p.reserved_publish_times)
    slots = generate_schedule_slots(
        start_local_date=start_dt,
        timezone=timezone,
        videos_per_day=videos_per_day,
        day_start_hhmm=day_start_time,
        count=len(new_files),
        reserved_rfc3339=reserved,
    )

    # Persist the scheduling prefs back to project
    p.videos_per_day = videos_per_day
    p.timezone = timezone
    p.day_start_time = day_start_time

    # Ask video metadata once (applies to all scheduled videos)
    console.print("\n[bold]Video defaults for this project (applies to ALL scheduled videos)[/bold]")
    console.print("[dim]Tip: these are saved to the project so you won't need to retype them after interruptions.[/dim]")

    if p.default_title is not None:
        console.print(f"\nTitle: [bold]{p.default_title}[/bold]")
        change = typer.confirm("Change title?", default=False)
        title = typer.prompt("Title").strip() if change else p.default_title
    else:
        title = typer.prompt("Title").strip()

    if p.default_description is not None:
        console.print(f"\nDescription: [bold]{p.default_description}[/bold]")
        change = typer.confirm("Change description?", default=False)
        description = typer.prompt("Description", default="", show_default=False) if change else p.default_description
    else:
        description = typer.prompt("Description", default="", show_default=False)

    if p.default_tags is not None:
        console.print(f"\nTags: [bold]{', '.join(p.default_tags)}[/bold]")
        change = typer.confirm("Change tags?", default=False)
        if change:
            tags_raw = typer.prompt("Tags (comma-separated, optional)", default="", show_default=False).strip()
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None
        else:
            tags = p.default_tags
    else:
        tags_raw = typer.prompt("Tags (comma-separated, optional)", default="", show_default=False).strip()
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else None

    if p.default_category_id is not None:
        console.print(f"\nCategory ID: [bold]{p.default_category_id}[/bold]")
        change = typer.confirm("Change category ID?", default=False)
        category_id = typer.prompt("Category ID (optional, leave blank)", default="", show_default=False).strip() or None if change else p.default_category_id
    else:
        category_id = typer.prompt("Category ID (optional, leave blank)", default="", show_default=False).strip() or None

    made_for_kids = typer.confirm('Is this video "made for kids"?', default=bool(getattr(p, "made_for_kids", False)))
    p.made_for_kids = made_for_kids

    # Persist defaults so re-runs (after limits/errors) don't require re-entry
    p.default_title = title
    p.default_description = description
    p.default_tags = tags
    p.default_category_id = category_id
    save_project(p)

    # Build YouTube client (unless dry-run)
    yt = None
    if not dry_run:
        try:
            from .youtube_api import load_credentials

            creds = load_credentials(
                client_secrets_path=Path(p.client_secrets_path).expanduser().resolve() if p.client_secrets_path else Path(""),
                token_path=token_path,
                scopes=DEFAULT_SCOPES,
            )
            if creds is None:
                raise typer.BadParameter("No token found; run: yt-scheduler auth <project>")
            yt = build_youtube_client(creds)
        except MissingDependencyError as e:
            console.print(str(e))
            raise typer.Exit(code=2)

    for idx, f in enumerate(new_files):
        publish_at = slots[idx]
        console.print(f"\n[bold]Video {idx+1}/{len(new_files)}[/bold]: {f.name}")
        console.print(f"Scheduled publishAt (UTC): {publish_at}")

        if dry_run:
            console.print("Dry-run: not uploading.")
            video_id = "DRY_RUN"
        else:
            assert yt is not None
            try:
                video_id = upload_video(
                    youtube=yt,
                    file_path=f,
                    title=title,
                    description=description,
                    tags=tags,
                    category_id=category_id,
                    made_for_kids=made_for_kids,
                    privacy_status="private",
                    publish_at_rfc3339=publish_at,
                )
            except Exception as e:
                # Common YouTube error when daily/channel upload cap is reached.
                # Example reason: "uploadLimitExceeded"
                if "uploadLimitExceeded" in str(e):
                    console.print(
                        "\n[bold red]Upload limit reached.[/bold red]\n"
                        "YouTube blocked further uploads for this account/channel (reason: uploadLimitExceeded).\n"
                        "Already-uploaded videos were saved to the project. Re-run this command later to continue."
                    )
                    raise typer.Exit(code=3)
                raise
            console.print(f"Uploaded: https://youtu.be/{video_id}")
            if throttle_seconds > 0 and idx < len(new_files) - 1:
                time.sleep(throttle_seconds)

        sha, size = hashes[f]
        p.uploaded.append(
            UploadedVideo(
                file_name=f.name,
                file_sha256=sha,
                file_size=size,
                uploaded_video_id=video_id,
                scheduled_publish_at=publish_at,
            )
        )
        p.reserved_publish_times.append(publish_at)
        save_project(p)

    console.print("\nDone. Project state updated.")


if __name__ == "__main__":
    app()


