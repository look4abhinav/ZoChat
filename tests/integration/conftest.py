import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("ZOCHAT_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="set ZOCHAT_RUN_INTEGRATION=1 to run")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
