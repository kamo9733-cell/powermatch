"""Generate web/i18n.json = tablesight/i18n/catalogs/<lang>.json (alert/state strings, single source of truth)
merged with web/ui_strings.json (UI chrome). Run: python web/gen_i18n.py"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAT = ROOT.parent / "tablesight" / "i18n" / "catalogs"
RTL = ["ar", "he", "fa", "ur"]


def build() -> dict:
    ui = json.loads((ROOT / "ui_strings.json").read_text(encoding="utf-8"))
    out = {"_rtl": RTL}
    for lang in ("en", "ar", "es", "de", "fr"):
        d = json.loads((CAT / f"{lang}.json").read_text(encoding="utf-8"))
        d.update(ui.get(lang, {}))
        out[lang] = d
    return out


if __name__ == "__main__":
    (ROOT / "i18n.json").write_text(json.dumps(build(), ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", ROOT / "i18n.json")
