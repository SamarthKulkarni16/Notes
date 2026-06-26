# journal-sync v2

Syncs markdown journal notes from the `Notes` GitHub repo into a `notes`
table in Supabase, embedding each note's content with Mistral so it can
later be retrieved as context by samarth-brain.

Replaces the original Simplenote-based sync, which is no longer usable
since Simplenote dropped direct password/API login.

## How it works

1. Lists every `.md` file inside the `notes/` folder of the `Notes` repo,
   using GitHub's contents API.
2. Compares each file's GitHub content SHA against what's already stored
   in Supabase (`github_sha` column). Unchanged files are skipped.
3. New or edited files are fetched, embedded with `mistral-embed`
   (1024 dimensions), and upserted into the `notes` table, keyed by
   `source` (the file's path) so edits update the existing row instead
   of creating a duplicate.
4. If any file fails to sync, the script exits with a non-zero code so
   the GitHub Actions run shows as failed — that file will simply be
   retried on the next run, since its SHA still won't match.

## One-time setup

### 1. Database

Already done if you ran the new `schema.sql` and the `github_sha`
column patch. The `notes` table should have:
`id, content, source, embedding, note_created_at, github_sha, synced_at`.

### 2. Create a read-only GitHub token for this job

This is separate from the token your journal site itself uses (that one
needs write access; this one only needs to read).

- GitHub → Settings → Developer settings → Personal access tokens →
  Fine-grained tokens → Generate new token
- Repository access: only the `Notes` repo
- Permissions → Contents: **Read-only**
- Copy the token

### 3. Add GitHub Actions secrets

In the `Notes` repo → Settings → Secrets and variables → Actions →
New repository secret. Add all of these:

| Secret name        | Value                                      |
|---------------------|---------------------------------------------|
| `GH_NOTES_TOKEN`    | the read-only token from step 2             |
| `GH_NOTES_OWNER`    | `SamarthKulkarni16`                          |
| `GH_NOTES_REPO`     | `Notes`                                      |
| `SUPABASE_URL`      | your Supabase project URL                    |
| `SUPABASE_KEY`      | Supabase **service role** key                |
| `MISTRAL_API_KEY`   | your Mistral API key                         |

### 4. Add these files to the repo

Place at the root of the `Notes` repo:
- `sync.py`
- `requirements.txt`
- `.github/workflows/sync.yml`

(`schema.sql` and `test_sync_logic.py` are optional to commit — they're
not needed at runtime, but useful to keep for reference/re-testing.)

### 5. Run it once manually to confirm

Repo → Actions tab → "Journal sync" workflow → Run workflow (button on
the right) → Run workflow again to confirm.

Check the run's logs for `Synced: notes/...` lines, then check the
`notes` table in Supabase for new rows.

## Schedule

Runs automatically every Monday at 00:00 UTC (5:30 AM IST). You can
always trigger it manually from the Actions tab any time via
"Run workflow".

## Not yet done

samarth-brain's retrieval code currently only searches the `memories`
table. To make journal content usable as AI context, you'll need a
Postgres function (cosine distance `<=>` on `embedding`, same pattern
as whatever already exists for `memories`) that also searches `notes`,
plus a small update to samarth-brain's query code to call it.
