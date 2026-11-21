import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="integration tests need DATABASE_URL (run make test-integration)")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)
