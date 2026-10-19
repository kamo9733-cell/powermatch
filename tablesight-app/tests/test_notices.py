import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("gen_notices", Path(__file__).parents[1] / "scripts" / "gen_notices.py")
gn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gn)


def test_deny_regex_catches_gpl_spellings_but_not_lgpl_or_permissive():
    for bad in ("GNU GPL", "GPLv3", "GNU General Public License v3 (GPLv3)", "AGPL-3.0", "SSPL"):
        assert gn.DENY.search(bad) and not gn.WEAK.search(bad), bad
    for ok in ("MIT", "Apache-2.0", "BSD-3-Clause", "Apache-2.0 OR BSD-3-Clause"):
        assert not gn.DENY.search(ok), ok
    assert gn.WEAK.search("LGPL v3") and gn.WEAK.search("MPL-2.0")


def test_runtime_closure_excludes_dev_tools_and_runs_clean():
    names = set(gn.closure(gn.ROOTS))
    assert "pytest" not in names and "ruff" not in names and "playwright" not in names
    assert gn.main() == 0
