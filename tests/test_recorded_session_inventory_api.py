from fastapi.testclient import TestClient

from market_lab.api import create_app
from market_lab.storage import initialize, make_engine


def test_inventory_endpoint_empty_and_missing_config(tmp_path):
    engine = make_engine("sqlite:///" + (tmp_path / "inventory-api.db").as_posix())
    initialize(engine)
    with TestClient(create_app(engine)) as client:
        response = client.get("/api/recorded-session-inventory")
        assert response.status_code == 200 and response.json() == {"rows": []}
        assert client.get("/api/recorded-session-inventory?config_id=999").status_code == 404
