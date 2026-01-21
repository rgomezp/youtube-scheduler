# youtube-scheduler

Interactive CLI to **upload and schedule videos** using the **YouTube Data API v3**, while keeping data isolated per “project” (so multiple channels/projects don’t mix).

## What you get

- **Project isolation**: each project is a separate JSON file under `~/.youtube-scheduler/projects/`
- **Guided setup**: `yt-scheduler init` walks you through what to do in Google Cloud Console
- **Upload directory workflow**: point the CLI at a folder you pre-fill with videos
- **No re-uploads**: the CLI hashes files and skips ones already uploaded in that project
- **Even scheduling**: you choose “videos per day”; it spaces slots evenly (e.g. 3/day → every 8 hours)

## Install (local)

From this repo:

Install pipx:
```
brew install pipx
pipx ensurepath
```

```bash
pipx install -e ".[youtube]"
```

## Quick start

Create a project and follow the prompts:

```bash
yt-scheduler init
```

Authenticate (if you didn’t do it during init):

```bash
yt-scheduler auth <project>
```

Upload + schedule new videos found in a directory:

```bash
yt-scheduler upload <project> --directory /path/to/videos
```

Dry-run to preview the scheduling plan without uploading:

```bash
yt-scheduler upload <project> --directory /path/to/videos --dry-run
```

List projects:

```bash
yt-scheduler projects list
```

## Developing
```bash
cd youtube-scheduler

python3 -m venv .venv
source .venv/bin/activate

pip install -U pip
pip install -e ".[youtube]"
```

### Why this works:
`pip install -e .` creates a live linke from: `.venv/site-packages/youtube_scheduler → ./src/youtube_scheduler`

So when you edit: `src/youtube_scheduler/cli.py`

Your CLI immediately reflects the change.

### How to run during development

Option A:
```bash
yt-scheduler --help
```

Option B:
```bash
python -m youtube_scheduler.cli
```

### When do you need to reinstall (globally)?
Only if you change:

- pyproject.toml dependencies
- entry points ([project.scripts])
- extras ([project.optional-dependencies])

Then run:
```bash
pip install -e ".[youtube]"
```

### Sanity check
```bash
which yt-scheduler
```

You should see:
```
youtube-scheduler/.venv/bin/yt-scheduler
```
If yes -> Perfect dev setup

## Notes / recommendations (for approval)

- The CLI prompts **title/description/tags** once and applies it to all scheduled uploads. If you want it even faster, we can add a per-project **metadata template** stored in the project JSON.
- The CLI asks whether to start scheduling **today** or on a **future date** (format: `YYYY-MM-DD`).
