import copy
import json

import pytest

from tablesight.labeling import import_corrections, new_clip, read_jsonl, summarise, validate_record
from tablesight.labeling.cli import main


def _errs(r):
    return [i for i in validate_record(r) if i.level == "error"]


def _customer(**kw):
    c = new_clip("c1", "customer", "customer-consent-agreement", 1280, 720, 10, 100,
                 created_at="2026-01-01T00:00:00+00:00", collected_at="2026-01-01T00:00:00+00:00")
    c["lineage"]["faces_blurred"] = True
    c["lineage"]["consent"] = {"obtained": True, "scope": ["eval"], "recorded_at": "2026-01-01T00:00:00Z",
                               "evidence_ref": "contract-17"}
    c["tracks"] = [{"pid": 1, "role": "staff", "boxes": [{"f": 0, "box": [10, 10, 50, 100]},
                                                          {"f": 5, "box": [12, 10, 52, 100]}]}]
    c["lineage"].update(kw)
    return c


def test_valid_customer_clip_passes_and_is_not_training_eligible_by_default():
    c = _customer()
    assert _errs(c) == []
    assert summarise([c])["training_eligible"] == 0


def test_training_scope_needs_consent_evidence():
    c = _customer()
    c["lineage"]["consent"]["scope"] = ["eval", "training"]
    assert _errs(c) == [] and summarise([c])["training_eligible"] == 1
    c["lineage"]["consent"]["evidence_ref"] = None
    assert any("evidence" in i.path for i in _errs(c))


def test_customer_without_consent_is_rejected():
    c = _customer()
    c["lineage"]["consent"]["obtained"] = False
    assert any(i.path == "lineage.consent.obtained" for i in _errs(c))


@pytest.mark.parametrize("lic", ["CC-BY-NC-4.0", "research-only", "GPL-3.0", "", None])
def test_bad_licences_are_rejected(lic):
    c = _customer()
    c["lineage"]["licence"] = lic
    assert any(i.path == "lineage.licence" for i in _errs(c))


def test_covert_capture_and_minors_rules():
    c = _customer()
    c["lineage"]["covert_capture"] = True
    assert any("covert" in i.path for i in _errs(c))
    c = _customer(contains_minors=True)
    c["lineage"]["consent"]["scope"] = ["training"]
    assert any("minors" in i.msg for i in _errs(c))


def test_missing_lineage_is_error():
    c = _customer()
    del c["lineage"]
    assert any(i.path == "lineage" for i in _errs(c))


def test_track_validation():
    c = _customer()
    c["tracks"][0]["boxes"][1]["f"] = 0                     # not increasing
    c["tracks"].append({"pid": 1, "role": "chef", "boxes": [{"f": 200, "box": [5, 5, 4, 9]}]})
    paths = {i.path for i in _errs(c)}
    assert "tracks[0].boxes[1].f" in paths and "tracks[1].pid" in paths
    assert "tracks[1].role" in paths and "tracks[1].boxes[0].f" in paths
    assert "tracks[1].boxes[0].box" in paths


def test_synthetic_clip_flags_and_non_object():
    s = new_clip("s", "synthetic", "synthetic-cc0", 640, 360, 10, 10, created_at="2026-01-01T00:00:00Z",
                 collected_at="2026-01-01T00:00:00Z")
    assert _errs(s) == []
    s2 = copy.deepcopy(s)
    s2["lineage"]["synthetic"] = False
    assert _errs(s2)
    assert _errs("nope") and _errs({"record_type": "x", "schema_version": 1})


def test_cli_new_validate_summarise_roundtrip(tmp_path, capsys):
    f = tmp_path / "a.jsonl"
    assert main(["new", "--out", str(f), "--clip-id", "s1", "--from-synth", "crossing", "--seed", "3",
                 "--at", "2026-01-01T00:00:00+00:00"]) == 0
    assert main(["validate", str(f)]) == 0
    capsys.readouterr()
    assert main(["summarise", str(f)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["synthetic_clips"] == 1 and s["tracks_by_role"] == {"guest": 2, "staff": 2}
    # deterministic output
    g = tmp_path / "b.jsonl"
    main(["new", "--out", str(g), "--clip-id", "s1", "--from-synth", "crossing", "--seed", "3",
          "--at", "2026-01-01T00:00:00+00:00"])
    assert f.read_text() == g.read_text()


def test_cli_validate_fails_on_unconsented_skeleton_and_bad_json(tmp_path):
    f = tmp_path / "a.jsonl"
    main(["new", "--out", str(f), "--clip-id", "x", "--source", "customer",
          "--licence", "customer-consent-agreement"])
    assert main(["validate", str(f)]) == 1
    f.write_text("{not json\n")
    assert main(["validate", str(f)]) == 1


def test_import_manager_corrections(tmp_path):
    rows = [
        {"id": 1, "org_id": "org-a", "location_id": "loc1", "kind": "role",
         "payload": json.dumps({"role": "staff", "feature": [0.6, 0.6, 0.3]}),
         "consent_training": 0, "t": 1.0},
        {"id": 2, "org_id": "org-a", "location_id": "loc1", "kind": "table_empty",
         "payload": {"table_id": "T1"}, "consent_training": 1, "t": 2.0},
        {"id": 3, "org_id": "org-a", "location_id": "loc1", "kind": "role",
         "payload": {"role": "chef", "feature": [2, 0, 0]}, "t": 3.0},
        {"id": 4, "org_id": "org-a", "location_id": "loc1", "kind": "mystery", "payload": {}, "t": 4},
    ]
    src = tmp_path / "c.json"
    src.write_text(json.dumps(rows))
    good, bad = import_corrections(src)
    assert [g["kind"] for g in good] == ["role", "table_empty"] and len(bad) == 2
    assert "org-a" not in json.dumps(good)                      # tenant id is pseudonymised
    assert [g["consent"]["training"] for g in good] == [False, True]
    out = tmp_path / "ann.jsonl"
    assert main(["import-corrections", "--input", str(src), "--out", str(out)]) == 0
    assert main(["import-corrections", "--input", str(src), "--out", str(out)]) == 0  # idempotent
    recs, _ = read_jsonl(out)
    assert len(recs) == 2 and main(["validate", str(out)]) == 0
    s = summarise(recs)
    assert s["corrections"] == 2 and s["training_eligible"] == 1
