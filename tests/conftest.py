import pytest
from fastapi.testclient import TestClient

from mock_crm.app import create_app
from pipeline.client import CRMClient
from pipeline.storage import Database


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.initialize()
    return database


@pytest.fixture
def api(monkeypatch):
    for name in ("CRM_SCHEMA_DRIFT", "CRM_RATE_LIMIT", "CRM_WEBHOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def crm(api):
    return CRMClient(api, sleep=lambda _: None)
