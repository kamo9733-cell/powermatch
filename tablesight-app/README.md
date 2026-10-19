# TableSight
AI floor intelligence for hospitality. See `CLAUDE.md` for the full build brief and `docs/PROGRESS.md` for status.
```
pip install -e ".[dev]" && pytest -q     # core, platform and browser tests (UI tests skip if chromium is missing)
TABLESIGHT_VAULT_KEY=$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())') python -m tablesight.platform
```
Static marketing site + demo: `site/index.html`. Self-host: `deploy/docker-compose.yml`.
