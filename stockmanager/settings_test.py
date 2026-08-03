"""Settings for the test suite.

The environment is populated *before* `stockmanager.settings` is imported —
which is the whole point of this module. A root conftest.py cannot do this:
pytest-django imports the settings module during
`pytest_load_initial_conftests`, before conftest.py is loaded.

`setdefault` means a real environment variable still wins, so CI can point
the suite at another database without editing this file.
"""

import os

os.environ.setdefault("SECRET_KEY", "insecure-key-for-tests-only")
os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# pytest-django appends "testserver" to ALLOWED_HOSTS itself; naming it here
# only produces a duplicate entry.
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:3000")

from stockmanager.settings import *  # noqa: E402,F401,F403
