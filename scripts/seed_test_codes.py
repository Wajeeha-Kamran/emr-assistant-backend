"""
Seeds the ICD-10/CPT reference codes into the TEST database.

The test suite runs against a separate database (see tests/conftest.py), which
starts empty. TC-08's code-suggestion tests assert against the seeded reference
data, so that one table has to be populated there too.

This derives the test database name exactly the way conftest.py does — append
"_test" to the configured DATABASE_URL — so the two cannot disagree about which
database is being used.

Usage, from the repository root:
    .\\.venv\\Scripts\\python.exe -m scripts.seed_test_codes
"""

import os
import sys
from urllib.parse import urlparse, urlunparse

from dotenv import dotenv_values

raw = os.environ.get("DATABASE_URL") or dotenv_values(".env").get("DATABASE_URL")
if not raw:
    sys.exit("FATAL: DATABASE_URL is not set in the environment or in .env.")

parsed = urlparse(raw)
name = parsed.path.lstrip("/")
if not name.endswith("_test"):
    parsed = parsed._replace(path=f"/{name}_test")

os.environ["DATABASE_URL"] = urlunparse(parsed)
print(f"Seeding database: {urlparse(os.environ['DATABASE_URL']).path.lstrip('/')}")

# Imported only after the override, so the application binds to the test
# database rather than the development one.
from scripts.seed_codes import seed_codes  # noqa: E402

seed_codes()
