"""Emit THIRD_PARTY_NOTICES.md from installed distributions; fail on disallowed licences."""
import sys
from importlib.metadata import distributions

DENY = ("AGPL", "GPL-3", "GPL-2", "SSPL", "BUSL", "Commons Clause")
NEEDS_REVIEW = ("LGPL", "MPL", "EPL")


def lic(d) -> str:
    m = d.metadata
    return m.get("License-Expression") or m.get("License") or "; ".join(
        c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")) or "UNKNOWN"


def main() -> int:
    bad = 0
    print("# Third-party notices\n")
    for d in sorted(distributions(), key=lambda d: d.metadata["Name"].lower()):
        name, l = d.metadata["Name"], lic(d).splitlines()[0][:80]
        flag = ""
        if any(x in l for x in DENY) and "LGPL" not in l:
            flag, bad = " **DISALLOWED**", bad + 1
        elif any(x in l for x in NEEDS_REVIEW):
            flag = " (review: weak copyleft)"
        print(f"- {name} {d.version}: {l}{flag}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
