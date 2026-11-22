from datetime import date

from ingest.pipeline import normalize


def test_nullable_values_and_exact_money():
    day = date(2025, 11, 3)
    row = normalize({
        "trip_id": "example", "trip_start_timestamp": "2025-11-03T21:45:00.000",
        "pickup_community_area": "", "dropoff_community_area": "78",
        "trip_seconds": "-3", "trip_miles": "NaN", "fare": "2.50", "trip_total": "10.23",
    }, day)
    assert row["trip_hour"] == 21
    assert row["pickup_zone"] == row["dropoff_zone"] == 0
    assert row["duration"] is None and row["miles"] is None
    assert (row["fare_cents"], row["amount_cents"]) == (250, 1023)


def test_wrong_day_or_missing_id():
    day = date(2025, 11, 3)
    assert normalize({"trip_id": "a", "trip_start_timestamp": "2025-11-04"}, day) is None
    assert normalize({"trip_id": "", "trip_start_timestamp": "2025-11-03"}, day) is None
