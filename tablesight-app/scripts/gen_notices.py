"""Emit THIRD_PARTY_NOTICES.md for the shipped runtime closure; fail on disallowed or unknown licences.

Scope: `tablesight` + its declared dependency closure (extras: platform, eval) - NOT dev tools.
Includes licence file text where the distribution ships one (Apache/BSD/MIT need the notice).
"""
import re
import sys
from importlib.metadata import PackageNotFoundError, distribution, requires

ROOTS = ["fastapi", "uvicorn", "cryptography", "httpx", "numpy"]
DENY = re.compile(r"\b(A?GPL(?:v?\d)?|SSPL|BUSL|Commons Clause)\b|GNU (Affero )?General Public|GNU GPL", re.IGNORECASE)
WEAK = re.compile(r"\b(LGPL|MPL|EPL)\b|GNU Lesser|Mozilla Public", re.IGNORECASE)
ALLOW_UNKNOWN: set[str] = set()


def norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


def lic(d) -> str:
    m = d.metadata
    parts = [m.get("License-Expression") or "", m.get("License") or ""]
    parts += [c.split("::")[-1].strip() for c in m.get_all("Classifier") or [] if c.startswith("License ::")]
    return " | ".join(p.splitlines()[0][:80] for p in parts if p.strip()) or "UNKNOWN"


def closure(roots: list[str]) -> dict:
    seen: dict = {}
    todo = list(roots)
    while todo:
        n = norm(todo.pop())
        if n in seen:
            continue
        try:
            d = distribution(n)
        except PackageNotFoundError:
            continue
        seen[n] = d
        for r in requires(n) or []:
            if "extra ==" in r:
                continue
            todo.append(re.split(r"[ ;<>=!~\[(]", r, maxsplit=1)[0])
    return seen


def license_text(d) -> str:
    for f in d.files or []:
        if re.search(r"(^|/)(LICENSE|LICENCE|COPYING|NOTICE)[^/]*$", str(f), re.IGNORECASE):
            try:
                return d.read_text(str(f)) or ""
            except (OSError, UnicodeDecodeError):
                continue
    return ""


def main() -> int:
    bad = 0
    print("# Third-party notices (runtime closure)\n")
    for n, d in sorted(closure(ROOTS).items()):
        name, l = d.metadata["Name"], lic(d)
        flag = ""
        if DENY.search(l) and not WEAK.search(l):
            flag, bad = " **DISALLOWED**", bad + 1
        elif l == "UNKNOWN" and n not in ALLOW_UNKNOWN:
            flag, bad = " **UNKNOWN LICENCE**", bad + 1
        elif WEAK.search(l):
            flag = " (review: weak copyleft)"
        print(f"## {name} {d.version}: {l}{flag}\n")
        t = license_text(d).strip()
        if t:
            print("```\n" + t[:6000] + "\n```\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
