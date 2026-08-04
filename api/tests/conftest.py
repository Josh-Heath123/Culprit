"""Loads api/.env before any test module is collected — some modules
(e.g. app/auth/config.py) read required env vars at import time, and
conftest.py is guaranteed to run before pytest imports test files in
whatever order it discovers them, unlike relying on one test file's own
imports (e.g. app.main's own load_dotenv() call) happening to run first.
"""

from dotenv import load_dotenv

load_dotenv()
