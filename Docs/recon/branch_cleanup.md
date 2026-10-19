# Branch state and cleanup commands (for you to run — nothing here was executed)

## Findings (from `git` history, read-only)

- Working branch for this phase: `claude/confident-einstein-9dzcgf` (the session's
  designated branch, created from the same HEAD as `main`). It is used in place of
  `fix/casualties-flow`; the content is the same idea (a feature branch off the
  current HEAD, not `main` and not `dev`).
- Phase commits `82bdaa5` … `6bd1dad` (Step 1 fixes, housekeeping, baseline doc)
  live on **`main`** (`origin/main` = `6bd1dad`) and on the working branch. They are
  **not on `dev`**. Commit `1c9b5f7` ("ignore database dump artifacts") is not in
  any branch this session can see (it is probably only in your local clone, unpushed).
- `origin/dev` = `8b9c5f9`. Divergence: `main` has 22 commits `dev` lacks; `dev` has 8
  commits `main` lacks (summary-flow audit work + `docs: casualty fix phase 0 recon`).
- Last two merges of `dev` into `main`: `4bb8991` and `3934487` (both 2026-10-08).
  Every commit after `3934487` was committed straight on `main`, which breaks the
  "dev for development, main for deploy" rule: `f8f82e0` (Oct 8), `6b96690`…`dc9fb59`
  (Oct 8), `8d93bca`…`0db63a4` (Oct 14), … up to `6bd1dad` (Oct 19).
- The last commit of `main` that was **deployed** before today cannot be determined
  from history: there are no tags and no deploy notes in the repo. Candidates, newest
  first: `dc9fb59` (2026-10-08 14:18, last commit before the Oct 14 work) and
  `3934487` (last merge from `dev`). Use the commands below to find out which one the
  running images were built from, then set `$LastDeployed`.

## 1. Find the last deployed commit (read-only, run in PowerShell)

```powershell
cd "C:\Users\User\Desktop\lebanon-news-monitor\War-news"
git reflog show main --date=iso -30
docker image ls --format "{{.Repository}}:{{.Tag}}  {{.CreatedAt}}" | Select-String "war-news"
git log main --first-parent --format="%h %ad %s" --date=iso -40
```

Match the image `CreatedAt` of the deployment backend image against the commit dates.
Then set the variable once (replace the value with the real hash):

```powershell
$LastDeployed = "dc9fb59"
git cat-file -t $LastDeployed
```

## 2. Get all phase commits onto `dev` (a merge, no history rewrite)

```powershell
git fetch origin
git status --short
git checkout dev
git pull origin dev
git merge main --no-ff -m "Merge main into dev: casualty step 1 and housekeeping"
# resolve conflicts if any, run the tests on the dev stack, then:
git push origin dev
```

If you would rather keep `dev` linear, cherry-pick instead:
`git cherry-pick 82bdaa5 dffbb47 da807d2 01ffa48 6bd1dad` (plus `1c9b5f7` from your clone).

## 3. Return `main` to the last deployed commit (only if main must not carry phase commits)

This rewrites where `main` points, so it is deliberately a manual step. Prefer a
revert-free approach: keep `main` as is until `dev` is verified, then deploy by merging
`dev` into `main`. If you do want to roll `main` back:

```powershell
git checkout main
git branch main-backup-2026-10-19 main
git reset --hard $LastDeployed
git push origin main --force-with-lease
```

(`main-backup-2026-10-19` keeps the current tip reachable. Skip the push if nobody
else has pulled `main`.)

## 4. Rebuild the deployment stack from that `main` (for you only)

```powershell
git checkout main
git log -1 --oneline
docker compose -p war-news --env-file .env.main up -d --build
docker compose -p war-news --env-file .env.main ps
```

## 5. Continue the casualties work from `dev`

```powershell
git checkout dev
git checkout -b fix/casualties-flow
git merge claude/confident-einstein-9dzcgf
```

After the fix is verified on the dev stack: merge `fix/casualties-flow` into `dev`,
then `dev` into `main`, then step 4.
