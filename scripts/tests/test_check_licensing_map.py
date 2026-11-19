# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

"""scripts/check_licensing_map.py: LICENSING.md's table and REUSE agree.

The real table is parsed here; the REUSE report is built by hand, in the
shape `reuse lint --json` gives, so the test needs no tool. The real report
is checked in `just lint` and CI's lint job.
"""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_licensing_map as m

ROWS_TEXT = m.LICENSING.read_text(encoding="utf-8")


def entry(path: str, spdx: str) -> dict:
    return {
        "path": path,
        "copyrights": [{"value": "SPDX-FileCopyrightText: 2026 Joshua Heath"}],
        "spdx_expressions": [{"value": spdx, "is_valid": True}],
    }


#: One file under every path the real table names, with its licence.
FILES = [
    entry("extractors/python/culprit_extract_python/__init__.py", "Apache-2.0"),
    entry("extractors/node/src/index.js", "Apache-2.0"),
    entry("shared/culprit_model/subjects.py", "Apache-2.0"),
    entry("cli/testdata/fixtures/third-party/flask-tutorial/flaskr/db.py", "BSD-3-Clause"),
    entry("cli/testdata/fixtures/third-party/express-route-separation/index.js", "MIT"),
    entry("cli/testdata/fixtures/third-party/flask-tutorial/culprit.yaml", "AGPL-3.0-only"),
    entry(
        "cli/testdata/fixtures/third-party/express-route-separation/culprit.yaml", "AGPL-3.0-only"
    ),
    *[
        entry(f"{d}x.py", "AGPL-3.0-only")
        for d in [
            "api/",
            "worker/",
            "mcp_server/",
            "demo-services/",
            "frontend/",
            "cli/",
            "infra/",
            "deploy/",
            "scripts/",
            "docs/",
            "examples/",
            "claude-setup/",
            ".github/",
            ".claude/",
        ]
    ],
    entry("justfile", "AGPL-3.0-only"),
]


def report(files=FILES, compliant=True) -> dict:
    return {"files": copy.deepcopy(files), "summary": {"compliant": compliant}}


def rows():
    return m.parse_licensing(ROWS_TEXT)


def test_the_real_table_parses_into_its_rows():
    parsed = rows()
    assert [row.spdx for row in parsed] == [
        "Apache-2.0",
        "Apache-2.0",
        "Apache-2.0",
        "BSD-3-Clause",
        "MIT",
        "AGPL-3.0-only",
        "AGPL-3.0-only",
    ]
    assert parsed[-1].root_files


def test_a_report_that_matches_the_table_agrees():
    assert m.check(report(), rows()) == []


def test_a_file_under_the_wrong_licence_is_named():
    files = [*FILES, entry("shared/culprit_model/new.py", "AGPL-3.0-only")]
    assert m.check(report(files), rows()) == [
        "shared/culprit_model/new.py: REUSE says AGPL-3.0-only, LICENSING.md says Apache-2.0"
    ]


def test_the_most_specific_row_wins():
    # The fixture's manifest is named outright; the fixture's own files take
    # its directory's row, not cli/'s.
    files = [e for e in FILES if not e["path"].endswith("flask-tutorial/culprit.yaml")]
    files.append(
        entry("cli/testdata/fixtures/third-party/flask-tutorial/culprit.yaml", "BSD-3-Clause")
    )
    problems = m.check(report(files), rows())
    assert problems == [
        "cli/testdata/fixtures/third-party/flask-tutorial/culprit.yaml: "
        "REUSE says BSD-3-Clause, LICENSING.md says AGPL-3.0-only"
    ]


def test_a_file_under_no_row_is_named():
    files = [*FILES, entry("tools/new.py", "AGPL-3.0-only")]
    assert m.check(report(files), rows()) == ["tools/new.py: under no row of LICENSING.md's table"]


def test_a_row_naming_nothing_is_named():
    files = [e for e in FILES if not e["path"].startswith("deploy/")]
    assert m.check(report(files), rows()) == [
        "LICENSING.md names 'deploy/' (AGPL-3.0-only), which holds no file REUSE covers"
    ]


def test_a_non_compliant_report_fails():
    files = [*FILES, {"path": "api/new.py", "copyrights": [], "spdx_expressions": []}]
    problems = m.check(report(files, compliant=False), rows())
    assert (
        problems[0]
        == "REUSE reports the project not compliant; without copyright or licence: api/new.py"
    )


def test_two_licences_on_one_file_are_named():
    files = [e for e in FILES if e["path"] != "justfile"]
    both = entry("justfile", "AGPL-3.0-only")
    both["spdx_expressions"].append({"value": "MIT", "is_valid": True})
    assert m.check(report([*files, both]), rows()) == [
        "justfile: REUSE says AGPL-3.0-only + MIT, LICENSING.md says AGPL-3.0-only"
    ]


@pytest.mark.parametrize(
    "text",
    [
        "# Licensing\n\nNo table.\n",
        "| Path | Licence | SPDX | Full text |\n|---|---|---|---|\n| `x/` | ? | — | y |\n",
    ],
)
def test_a_table_that_cannot_be_read_cannot_pass(text):
    with pytest.raises(ValueError):
        m.parse_licensing(text)


def test_an_empty_report_fails():
    assert "REUSE reported no files" in m.check(report([]), rows())
