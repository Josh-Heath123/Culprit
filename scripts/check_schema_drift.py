#!/usr/bin/env python3
"""Fails if worker/app/db.py's Core Table columns drift from
api/app/db/models.py's ORM columns for the same tables.

worker and api are separate uv projects, each with their own `app`
package (see CLAUDE.md) — that rules out importing both schemas in one
process, so this shells out to each project's own venv to dump its own
table/column shape as JSON, then diffs the two dumps here. Wired into
CI as its own step in the typecheck job (.github/workflows/ci-cd.yml),
the same spot as the anomaly/RAG import-boundary check (`lint-imports`).

worker/app/db.py only mirrors the subset of api's tables/columns it
actually queries (see that file's own docstring) — this only fails on
an actual mismatch (a column worker declares that api doesn't have, or
a nullable/type mismatch on a shared column), never just because api
has more tables or columns than worker needs.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Both snippets intentionally use only stdlib + sqlalchemy so they run
# fine in either project's venv without extra deps, and print one JSON
# object to stdout so this script has a single, stable thing to parse.
API_DUMP_CODE = """
import json
from app.db.models import Base

out = {
    table_name: {
        col.name: {"type": str(col.type), "nullable": bool(col.nullable)}
        for col in table.columns
    }
    for table_name, table in Base.metadata.tables.items()
}
print(json.dumps(out))
"""

WORKER_DUMP_CODE = """
import json
from app.db import metadata

out = {
    table_name: {
        col.name: {"type": str(col.type), "nullable": bool(col.nullable)}
        for col in table.columns
    }
    for table_name, table in metadata.tables.items()
}
print(json.dumps(out))
"""


def _dump_schema(project_dir: str, code: str) -> dict:
    result = subprocess.run(
        ["uv", "run", "python", "-c", code],
        cwd=ROOT / project_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    api_schema = _dump_schema("api", API_DUMP_CODE)
    worker_schema = _dump_schema("worker", WORKER_DUMP_CODE)

    errors: list[str] = []
    for table_name, worker_columns in worker_schema.items():
        api_columns = api_schema.get(table_name)
        if api_columns is None:
            errors.append(
                f"{table_name}: declared in worker/app/db.py, no such table in api/app/db/models.py"
            )
            continue
        for col_name, worker_col in worker_columns.items():
            api_col = api_columns.get(col_name)
            if api_col is None:
                errors.append(
                    f"{table_name}.{col_name}: in worker/app/db.py, missing from api/app/db/models.py"
                )
                continue
            if worker_col["nullable"] != api_col["nullable"]:
                errors.append(
                    f"{table_name}.{col_name}: nullable={worker_col['nullable']} in worker, "
                    f"nullable={api_col['nullable']} in api"
                )
            if worker_col["type"] != api_col["type"]:
                errors.append(
                    f"{table_name}.{col_name}: type={worker_col['type']} in worker, "
                    f"type={api_col['type']} in api"
                )

    if errors:
        print(
            "Schema drift between worker/app/db.py and api/app/db/models.py:",
            file=sys.stderr,
        )
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    table_count = len(worker_schema)
    print(f"No schema drift: {table_count} worker table(s) match api's ORM columns.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
