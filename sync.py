"""
journal-sync v2 — GitHub-based journal sync into Supabase.

Reads markdown notes from the `notes/` folder of a GitHub repo,
detects new or edited files via GitHub's content SHA, embeds them
with Mistral, and upserts into the `notes` table in Supabase.

Required environment variables:
  GITHUB_TOKEN     - token with read access to the notes repo
  GITHUB_OWNER     - e.g. SamarthKulkarni16
  GITHUB_REPO      - e.g. Notes
  SUPABASE_URL
  SUPABASE_KEY     - service role key
  MISTRAL_API_KEY
"""

import os
import re
import sys
import base64
import requests
from datetime import datetime, timezone

from supabase import create_client
from mistralai.client import Mistral


GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ["GITHUB_REPO"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
MISTRAL_API_KEY = os.environ["MISTRAL_API_KEY"]

NOTES_PATH = "notes"
GITHUB_API = "https://api.github.com"

FILENAME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})\.md$")


def github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def list_note_files():
    """Return list of {name, path, sha} for every .md file in notes/."""
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{NOTES_PATH}"
    resp = requests.get(url, headers=github_headers())
    if resp.status_code == 404:
        print(f"No '{NOTES_PATH}' folder found yet in the repo. Nothing to sync.")
        return []
    resp.raise_for_status()
    items = resp.json()
    return [
        {"name": item["name"], "path": item["path"], "sha": item["sha"]}
        for item in items
        if item["type"] == "file" and item["name"].endswith(".md")
    ]


def fetch_file_content(path):
    """Fetch and decode the raw content of a single file."""
    url = f"{GITHUB_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    resp = requests.get(url, headers=github_headers())
    resp.raise_for_status()
    data = resp.json()
    raw = base64.b64decode(data["content"])
    return raw.decode("utf-8")


def parse_created_at(filename):
    """Extract a timestamp from a filename like 2026-06-26-073400.md."""
    m = FILENAME_RE.search(filename)
    if not m:
        return None
    year, month, day, hour, minute, second = (int(x) for x in m.groups())
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None


def get_existing_shas(supabase):
    """Map of source -> github_sha already stored in Supabase."""
    result = supabase.table("notes").select("source, github_sha").execute()
    return {row["source"]: row["github_sha"] for row in result.data}


def embed_text(mistral, text):
    resp = mistral.embeddings.create(model="mistral-embed", inputs=[text])
    return resp.data[0].embedding


def main():
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    mistral = Mistral(api_key=MISTRAL_API_KEY)

    files = list_note_files()
    print(f"Found {len(files)} note file(s) in '{NOTES_PATH}/'.")

    existing_shas = get_existing_shas(supabase)

    to_process = [
        f for f in files
        if existing_shas.get(f["path"]) != f["sha"]
    ]
    print(f"{len(to_process)} file(s) are new or changed since last sync.")

    failures = []

    for f in to_process:
        path = f["path"]
        try:
            content = fetch_file_content(path)

            if not content.strip():
                print(f"Skipping empty file: {path}")
                continue

            embedding = embed_text(mistral, content)
            created_at = parse_created_at(f["name"])

            supabase.table("notes").upsert(
                {
                    "content": content,
                    "source": path,
                    "embedding": embedding,
                    "note_created_at": created_at.isoformat() if created_at else None,
                    "github_sha": f["sha"],
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="source",
            ).execute()

            print(f"Synced: {path}")

        except Exception as e:
            print(f"FAILED to sync {path}: {e}", file=sys.stderr)
            failures.append(path)

    if failures:
        print(f"\n{len(failures)} file(s) failed and will retry next run:")
        for path in failures:
            print(f"  - {path}")
        sys.exit(1)

    print("\nSync complete. No failures.")


if __name__ == "__main__":
    main()
