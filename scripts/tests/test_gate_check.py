"""Throwaway: a deliberately failing test, to show the ruleset blocks a red gate.

Never merged; the pull request is closed and the branch deleted.
"""


def test_deliberately_fails():
    assert 1 == 2, "deliberately failing: the gate must block this pull request"
