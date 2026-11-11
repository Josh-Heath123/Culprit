"""The narrator — Phase 35 part 2, docs/DIAGNOSTIC_PLAN.md D8.

The one place in the system that talks to a language model. It renders a
stored, settled investigation into prose, and nothing else: it is given
the investigation as numbered evidence and no tools, makes one call per
attempt, and writes what came back only after
`culprit_model.narration.check` has held it to its input.

Two `lint-imports` contracts keep it in its place (worker/pyproject.toml):
only this package may reach a provider's client, and no deterministic
package may import it — so nothing downstream reads a narration.
"""
