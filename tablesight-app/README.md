# TableSight
AI floor intelligence for hospitality. See `CLAUDE.md` for the full build brief and `docs/PROGRESS.md` for status.
```
pip install -e . fastapi httpx cryptography pytest ruff && pytest -q     # core + platform tests
TABLESIGHT_VAULT_KEY=$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())') python -m tablesight.platform
```
Static marketing site + demo: `site/index.html`. Self-host: `deploy/docker-compose.yml`.
