import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated

from clickhouse_connect.driver.exceptions import ClickHouseError
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles

from api.db import connect, database_name


@asynccontextmanager
async def lifespan(app):
    app.state.client = None
    try:
        yield
    finally:
        if app.state.client:
            app.state.client.close()


app = FastAPI(title="Pulso Chicago", version="1.0", lifespan=lifespan)


def rows(request: Request, sql, params=None):
    try:
        if request.app.state.client is None:
            request.app.state.client = connect(database_name(os.getenv("PULSO_DATABASE", "pulso_local")))
        result = request.app.state.client.query(sql, parameters=params, settings={"max_execution_time": 8})
        return list(result.named_results())
    except (ClickHouseError, OSError) as error:
        raise HTTPException(503, "El motor OLAP no está disponible en este momento.") from error


def filters(
    start: date, end: date, zone: Annotated[int | None, Query(ge=0, le=77)] = None,
):
    if start > end or end - start > timedelta(days=30):
        raise HTTPException(422, "El rango debe contener de 1 a 31 días.")
    return {"start": start, "end": end, "zone": zone if zone is not None else 255}


DATE_FILTER = "trip_date BETWEEN {start:Date} AND {end:Date}"
ZONE_FILTER = "({zone:UInt8} = 255 OR pickup_zone = {zone:UInt8})"
METRICS = """sum(trips) AS journeys,
    round(toFloat64(sum(total_cents)) / nullIf(sum(known_total), 0) / 100, 2) AS average_total,
    round(sum(duration_seconds) / nullIf(sum(known_duration), 0) / 60, 2) AS average_minutes"""


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/api/metadata")
def metadata(request: Request):
    values = rows(request, "SELECT payload FROM dataset_metadata LIMIT 1")
    if not values:
        raise HTTPException(503, "Todavía no hay un lote validado.")
    import json
    return json.loads(values[0]["payload"])


@app.get("/api/overview")
def overview(request: Request, params: Annotated[dict, Depends(filters)]):
    predicate = f"{DATE_FILTER} AND {ZONE_FILTER}"
    summary = rows(request, f"SELECT {METRICS} FROM agg_zone_hour WHERE {predicate}", params)[0]
    zones = rows(request, f"""SELECT pickup_zone AS zone, sum(trips) AS journeys
        FROM agg_zone_hour WHERE {DATE_FILTER} GROUP BY pickup_zone ORDER BY journeys DESC""", params)
    timeline = rows(request, f"""SELECT trip_date AS day, sum(trips) AS journeys
        FROM agg_zone_hour WHERE {predicate} GROUP BY trip_date ORDER BY trip_date""", params)
    return {"summary": summary, "zones": zones, "timeline": timeline}


@app.get("/api/demand")
def demand(
    request: Request, params: Annotated[dict, Depends(filters)],
    hour: Annotated[int | None, Query(ge=0, le=23)] = None,
):
    return rows(request, f"""SELECT toDayOfWeek(trip_date) AS weekday, trip_hour AS hour,
        sum(trips) AS journeys FROM agg_zone_hour
        WHERE {DATE_FILTER} AND {ZONE_FILTER} AND ({{hour:UInt8}} = 255 OR trip_hour = {{hour:UInt8}})
        GROUP BY weekday, hour ORDER BY weekday, hour""", dict(params, hour=hour if hour is not None else 255))


@app.get("/api/flows")
def flows(request: Request, params: Annotated[dict, Depends(filters)]):
    result = rows(request, f"""SELECT dropoff_zone AS zone, sum(trips) AS journeys,
        round(100.0 * sum(trips) / nullIf(sum(sum(trips)) OVER (), 0), 2) AS share
        FROM agg_od_day WHERE {DATE_FILTER} AND {ZONE_FILTER}
        GROUP BY dropoff_zone ORDER BY journeys DESC, zone LIMIT 10""", params)
    return result


static_dir = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if static_dir.is_dir():
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")
