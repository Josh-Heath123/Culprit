"""scripts/check_security_doc.py: the real document passes, and each way a
"cannot" can go untested fails it."""

from pathlib import Path

import check_security_doc as doc


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "SECURITY.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_real_threat_model_passes() -> None:
    assert doc.check(doc.DEFAULT) == []


def test_a_cannot_that_names_no_test_fails(tmp_path: Path) -> None:
    path = write(tmp_path, "# Model\n\n- An attacker cannot do the thing.\n")
    (problem,) = doc.check(path)
    assert problem.line == 3 and "names no test" in problem.message


def test_a_test_that_does_not_exist_fails(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "- It cannot replay. `api/tests/test_agents_api.py::test_nothing_of_the_kind`\n",
    )
    (problem,) = doc.check(path)
    assert "defines no test_nothing_of_the_kind" in problem.message


def test_a_file_that_does_not_exist_fails(tmp_path: Path) -> None:
    path = write(tmp_path, "- It cannot. `cli/internal/nowhere_test.go::TestNothing`\n")
    (problem,) = doc.check(path)
    assert "does not exist" in problem.message


def test_a_go_test_and_a_python_test_both_resolve(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "- It cannot listen. `cli/cmd/culprit/listen_test.go::TestNothingInTheBinaryListens`\n"
        "- It cannot replay. `api/tests/test_agents_api.py::test_a_replayed_request_is_refused`\n",
    )
    assert doc.check(path) == []


def test_a_multi_line_item_is_one_block_and_a_new_item_is_another(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "- It cannot listen,\n"
        "  as tested by `cli/cmd/culprit/listen_test.go::TestNothingInTheBinaryListens`\n"
        "- And it cannot fly.\n",
    )
    (problem,) = doc.check(path)
    assert problem.line == 3


def test_code_fences_are_not_claims(tmp_path: Path) -> None:
    path = write(tmp_path, "```\nyou cannot see this\n```\n")
    assert doc.check(path) == []
