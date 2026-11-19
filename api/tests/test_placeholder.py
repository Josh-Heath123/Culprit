# SPDX-FileCopyrightText: 2026 Joshua Heath
# SPDX-License-Identifier: AGPL-3.0-only

def test_api_app_imports() -> None:
    from app.main import app

    assert app.title == "Culprit API"
