"""Tiny i18n: message catalogs, RTL flag, locale-aware formatting hooks. Timestamps stay UTC in storage."""
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CATALOG_DIR = Path(__file__).parent / "catalogs"
RTL = {"ar", "he", "fa", "ur"}


def load(lang: str) -> dict[str, str]:
    base = json.loads((CATALOG_DIR / "en.json").read_text(encoding="utf-8"))
    p = CATALOG_DIR / f"{lang}.json"
    if lang != "en" and p.exists():
        base.update(json.loads(p.read_text(encoding="utf-8")))  # missing keys fall back to English
    return base


def direction(lang: str) -> str:
    return "rtl" if lang.split("-")[0] in RTL else "ltr"


def t(lang: str, key: str, **kw) -> str:
    return load(lang).get(key, key).format(**kw)


def local_time(utc_ts: float, tz: str) -> datetime:
    return datetime.fromtimestamp(utc_ts, UTC).astimezone(ZoneInfo(tz))
