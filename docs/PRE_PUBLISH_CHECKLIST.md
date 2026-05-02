# Pre-publish checklist

Tick each item before `git push public main`. This file gets deleted after the public push.

## Secret rotation

- [ ] Rotate the GitHub PAT currently in local `.env` (`GITHUB_TOKEN=ghp_...`). Generate a new one at https://github.com/settings/tokens. Update `.env` and Secret Manager (`<TF_VAR_project_name>-github-token`).
- [ ] Rotate the Telegram bot token (`TELEGRAM_BOT_TOKEN=...`). Talk to [@BotFather](https://t.me/BotFather) → `/revoke` → `/newtoken` for the existing bot, OR create a new bot. Update `.env` and Secret Manager (`<TF_VAR_project_name>-telegram-bot-token`).

## Git history scans

- [ ] `git log --all -- .env` returns nothing (the `.env` file was never committed)
- [ ] `git log --all -- DESIGN.v2.md` shows the deletion commit but the latest tracked content is gone
- [ ] `git log --all -- spike/` shows the deletion commit
- [ ] `git log --all -- sample/` shows the deletion commit

## Sensitive-string greps

Each must return CLEAN (no matches outside of `.git`). Run all four:

- [ ] `grep -rn "gen-lang-client-" . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=.pytest_cache`
- [ ] `grep -rn "8481672863" . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=.pytest_cache`
- [ ] `grep -rn "pixelcanon" . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=__pycache__ --exclude-dir=.pytest_cache`
- [ ] `grep -rn "ghp_\|glpat-\|AAA[A-Z]" . --exclude-dir=.git --exclude-dir=.venv` (catches stray PATs / Telegram token prefixes)

## Coverage check

- [ ] `.env.example` lists every env var that `deploy.py` and `terraform` actually read. To verify:
  - `grep -hoE 'os\.environ\.get\("[A-Z_]+"\)' deploy.py agent.py local_run.py | sort -u`
  - `grep -hoE 'var\.[a-z_]+' deploy/terraform/*.tf | sort -u`
  - Every name from these lists must appear in `.env.example` (or be a known auto-set var like `GOOGLE_CLOUD_AGENT_ENGINE_ID`).

## Smoke tests

- [ ] `uv run pytest` — full suite green
- [ ] `PYTHONPATH=. uv run python local_run.py` — completes through to the first HITL pause
- [ ] `cd deploy/terraform && terraform plan -var=project_name=test -var=project=test-project -var=github_token=fake -var=telegram_bot_token=fake` — plan succeeds

## After all green

Delete this file:

```bash
git rm docs/PRE_PUBLISH_CHECKLIST.md
git commit -m "chore: remove pre-publish checklist (passed)"
```
