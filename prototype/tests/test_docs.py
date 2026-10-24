"""Doc drift: README's scenario table must list exactly one row per fixture in scenarios.json,
and docs/deployment-path.md must carry every adapter label word for word."""
import json
from pathlib import Path

from satyapan.adapters import Adapters

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
FIXTURES = ROOT / "data" / "fixtures" / "scenarios.json"
DEPLOYMENT = ROOT.parent / "docs" / "deployment-path.md"
ROOT_README = ROOT.parent / "README.md"


def fixture_scenarios():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))["scenarios"]


def readme_table_rows():
    lines = README.read_text(encoding="utf-8").splitlines()
    return [l for l in lines if l.startswith("|") and not set(l) <= {"|", "-", " "} and "---" not in l]


def test_every_scenario_has_exactly_one_readme_row():
    rows = readme_table_rows()
    for sc in fixture_scenarios():
        hits = [r for r in rows if sc["id"] in r]
        assert len(hits) == 1, f"{sc['id']} appears in {len(hits)} README table rows; expected exactly one"


def test_readme_row_states_the_expected_verdict():
    rows = readme_table_rows()
    for sc in fixture_scenarios():
        row = next(r for r in rows if sc["id"] in r)
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert sc["expect"] in cells, f"{sc['id']}: README row does not carry the expected verdict {sc['expect']}"


def test_no_stale_scenario_rows():
    import re
    ids = {sc["id"] for sc in fixture_scenarios()}
    first_cells = [r.strip("|").split("|")[0].strip() for r in readme_table_rows()]
    scenario_cells = [c for c in first_cells if re.fullmatch(r"S\d+\w*(-[\w-]+)+", c)]
    stale = [c for c in scenario_cells if c not in ids]
    assert not stale, f"README scenario rows not in scenarios.json: {stale}"
    assert len(scenario_cells) == len(ids), "README scenario table row count differs from scenarios.json"


def deployment_table_rows():
    lines = DEPLOYMENT.read_text(encoding="utf-8").splitlines()
    return [l for l in lines if l.startswith("|") and not set(l) <= {"|", "-", " "} and "---" not in l]


def test_deployment_path_carries_every_adapter_label_verbatim():
    text = DEPLOYMENT.read_text(encoding="utf-8")
    for label in Adapters.mocks().labels():
        for field in ("name", "owner", "production_source", "route"):
            assert label[field] in text, \
                f"deployment-path.md drifted from adapter {label['name']!r}: {field} {label[field]!r} not found verbatim"


def test_every_path_named_in_the_root_readme_exists():
    import re
    text = ROOT_README.read_text(encoding="utf-8")
    paths = set(re.findall(r"(?:docs|satyapan|deck|infra)/[\w./-]*", text))
    assert paths, "no repo-relative paths found in the root README"
    missing = sorted(p for p in paths if not (ROOT.parent / p.rstrip("/.")).exists())
    assert not missing, f"root README names paths that do not exist: {missing}"


def test_deployment_table_has_exactly_one_row_per_adapter():
    rows = deployment_table_rows()
    labels = Adapters.mocks().labels()
    for label in labels:
        hits = [r for r in rows if label["name"] in r]
        assert len(hits) == 1, f"{label['name']!r} appears in {len(hits)} deployment-path.md table rows; expected exactly one"
    adapter_rows = [r for r in rows if any(label["name"] in r for label in labels)]
    assert len(adapter_rows) == len(labels), "deployment-path.md adapter table row count differs from the engine's adapters"
