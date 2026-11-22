import os
from datetime import date
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from api.db import connect
from api.main import app
from ingest.pipeline import SCHEMA, digest, load, update_json

pytestmark = pytest.mark.skipif(os.getenv("RUN_CLICKHOUSE_TESTS") != "1", reason="Requiere ClickHouse local")


def test_full_load_and_api(tmp_path, monkeypatch):
    database = "pulso_test_" + uuid4().hex[:12]
    date_a, date_b = date(2025, 11, 3), date(2025, 11, 4)
    files = []
    for day, values in (
        (date_a, [("id-a", 5, 7, 600, 1200), ("id-b", 5, 0, 1200, None), ("id-c", 0, 7, None, 2500)]),
        (date_b, [("id-a", 5, 7, 600, 1200)]),
    ):
        source = tmp_path / f"{day}.parquet"
        records = [dict(trip_id=identity, trip_date=day, trip_hour=8,
                        pickup_zone=pickup, dropoff_zone=dropoff, duration=duration,
                        miles=None, fare_cents=None, amount_cents=amount)
                   for identity, pickup, dropoff, duration, amount in values]
        pq.write_table(pa.Table.from_pylist(records, schema=SCHEMA), source)
        files.append(dict(file=source.name, sha256=digest(source), accepted_rows=len(records)))
    update_json(tmp_path / "manifest.json", dict(start=str(date_a), end=str(date_b), files=files))
    monkeypatch.setenv("PULSO_DATABASE", database)
    try:
        load(tmp_path, database)
        with pytest.raises(ValueError, match="ya existe"):
            load(tmp_path, database)
        with TestClient(app) as browser:
            assert browser.get("/healthz").json() == {"status": "ok"}
            metadata = browser.get("/api/metadata").json()
            assert metadata["rows"] == 3 and metadata["duplicate_rows"] == 1
            params = {"start": str(date_a), "end": str(date_b), "zone": 5}
            overview = browser.get("/api/overview", params=params)
            assert overview.status_code == 200, overview.text
            assert overview.json()["summary"] == {"journeys": 2, "average_total": 12.0, "average_minutes": 15.0}
            assert browser.get("/api/demand", params={**params, "hour": 8}).json() == [
                {"weekday": 1, "hour": 8, "journeys": 2}]
            assert browser.get("/api/demand", params={**params, "hour": 9}).json() == []
            assert browser.get("/api/flows", params=params).json() == [
                {"zone": 0, "journeys": 1, "share": 50.0}, {"zone": 7, "journeys": 1, "share": 50.0}]
            assert browser.get("/api/flows", params={**params, "zone": 78}).status_code == 422
    finally:
        with connect(loading=True) as client:
            client.command("DROP DATABASE IF EXISTS " + database)
