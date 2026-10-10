import pytest


@pytest.fixture
def device():
    return {
        "host": "192.0.2.1", "user": "automation", "port": 22,
        "version": "1.4", "source": "examples/1.4/config.boot",
        "management_interface": "eth0", "secrets": {},
        "healthcheck_targets": ["192.0.2.254"],
    }
