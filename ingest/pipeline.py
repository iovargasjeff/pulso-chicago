import argparse
import csv
import hashlib
import io
import json
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq

from api.db import connect, database_name

SOURCE = "https://data.cityofchicago.org/resource/6dvr-xwnh.csv"
SOURCE_ID = "6dvr-xwnh"
COLUMNS = (
    "trip_id", "trip_start_timestamp", "pickup_community_area", "dropoff_community_area",
    "trip_seconds", "trip_miles", "fare", "trip_total",
)
SCHEMA = pa.schema([
    ("trip_id", pa.string()), ("trip_date", pa.date32()), ("trip_hour", pa.uint8()),
    ("pickup_zone", pa.uint8()), ("dropoff_zone", pa.uint8()), ("duration", pa.uint32()),
    ("miles", pa.float32()), ("fare_cents", pa.int64()), ("amount_cents", pa.int64()),
])


def days_between(start, end):
    return (start + timedelta(days=offset) for offset in range((end - start).days + 1))


def number(value, *, maximum, scale=1, integer=True):
    try:
        parsed = Decimal(value or "NaN") * scale
        if parsed.is_finite() and 0 <= parsed <= maximum:
            if integer and parsed == parsed.to_integral_value():
                return int(parsed)
            if not integer:
                return float(parsed)
    except (InvalidOperation, TypeError, ValueError):
        pass
    return None


def normalize(raw, day):
    try:
        start = datetime.fromisoformat(raw["trip_start_timestamp"])
        trip_id = raw["trip_id"].strip()
        if start.date() != day or not trip_id:
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    return {
        "trip_id": trip_id, "trip_date": day, "trip_hour": start.hour,
        "pickup_zone": number(raw.get("pickup_community_area"), maximum=77) or 0,
        "dropoff_zone": number(raw.get("dropoff_community_area"), maximum=77) or 0,
        "duration": number(raw.get("trip_seconds"), maximum=86400),
        "miles": number(raw.get("trip_miles"), maximum=1000, integer=False),
        "fare_cents": number(raw.get("fare"), maximum=1_000_000, scale=100),
        "amount_cents": number(raw.get("trip_total"), maximum=1_000_000, scale=100),
    }


def request_page(client, predicate, page_size):
    for attempt in range(5):
        try:
            response = client.get(SOURCE, params={
                "$select": ",".join(COLUMNS), "$where": predicate,
                "$order": "trip_start_timestamp,trip_id", "$limit": page_size,
            })
            response.raise_for_status()
            reader = csv.DictReader(io.StringIO(response.text))
            if not set(COLUMNS).issubset(reader.fieldnames or []):
                raise ValueError("La API devolvió columnas inesperadas.")
            return list(reader)
        except (httpx.TransportError, httpx.HTTPStatusError) as error:
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in (408, 429, 500, 502, 503, 504):
                raise
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def update_json(target, payload):
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(target)


def extract_day(client, day, output, page_size):
    file = output / f"{day}.parquet"
    progress = file.with_suffix(".json")
    if progress.exists() and file.exists():
        previous = json.loads(progress.read_text(encoding="utf-8"))
        if digest(file) == previous["sha256"]:
            return previous

    base = f"trip_start_timestamp >= '{day}T00:00:00' AND trip_start_timestamp < '{day + timedelta(days=1)}T00:00:00'"
    cursor = None
    seen = set()
    counters = Counter()
    temp = file.with_suffix(".part")
    with pq.ParquetWriter(temp, SCHEMA, compression="zstd") as writer:
        while True:
            predicate = base
            if cursor:
                stamp, trip_id = (item.replace("'", "''") for item in cursor)
                predicate += f" AND (trip_start_timestamp > '{stamp}' OR (trip_start_timestamp = '{stamp}' AND trip_id > '{trip_id}'))"
            page = request_page(client, predicate, page_size)
            if not page:
                break
            last = (page[-1]["trip_start_timestamp"], page[-1]["trip_id"])
            if not all(last) or (cursor is not None and last <= cursor):
                raise ValueError(f"La paginación no avanzó para {day}.")
            cursor = last
            batch = []
            for raw in page:
                counters["source_rows"] += 1
                row = normalize(raw, day)
                if row is None or row["trip_id"] in seen:
                    counters["discarded_rows"] += 1
                    continue
                seen.add(row["trip_id"])
                counters["accepted_rows"] += 1
                counters["unknown_pickup"] += row["pickup_zone"] == 0
                batch.append(row)
            if batch:
                writer.write_table(pa.Table.from_pylist(batch, schema=SCHEMA))
    if not counters["accepted_rows"]:
        raise ValueError(f"El día {day} no contiene viajes válidos.")
    temp.replace(file)
    summary = {"day": str(day), "file": file.name, "sha256": digest(file),
               **{key: counters[key] for key in ("source_rows", "discarded_rows", "accepted_rows", "unknown_pickup")}}
    update_json(progress, summary)
    print(f'{day}: {summary["accepted_rows"]:,} viajes', flush=True)
    return summary


def extract(start, end, output, page_size, workers):
    output.mkdir(parents=True, exist_ok=True)
    token = os.getenv("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}
    with httpx.Client(timeout=85, headers=headers) as client, ThreadPoolExecutor(max_workers=workers) as pool:
        def extract_window(day):
            return extract_day(client, day, output, page_size)

        daily = list(pool.map(extract_window, days_between(start, end)))
    manifest = {
        "source": SOURCE, "source_id": SOURCE_ID, "source_columns": COLUMNS,
        "start": str(start), "end": str(end), "timezone": "America/Chicago",
        "assembled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_rows": sum(day["source_rows"] for day in daily),
        "discarded_rows": sum(day["discarded_rows"] for day in daily),
        "files": daily,
    }
    update_json(output / "manifest.json", manifest)


def load(output, database):
    database = database_name(database)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    with connect(loading=True) as client:
        exists = client.query("EXISTS DATABASE " + database).result_rows[0][0]
        if exists:
            raise ValueError("El esquema ya existe. Usa un nombre nuevo para cada intento.")
        client.command("CREATE DATABASE " + database)
        schema = Path(__file__).resolve().parents[1] / "sql" / "schema.sql"
        for statement in schema.read_text(encoding="utf-8").format(database=database).split(";"):
            if statement.strip():
                client.command(statement)
        fact = database + ".fact_trips"
        stage = database + ".staging_trips"
        client.command(f"CREATE TABLE {stage} AS {fact}")
        for entry in manifest["files"]:
            source = output / Path(entry["file"]).name
            if digest(source) != entry["sha256"]:
                raise ValueError(f"Checksum inválido: {source.name}")
            for batch in pq.ParquetFile(source).iter_batches(batch_size=80_000):
                client.insert_arrow(stage, pa.Table.from_batches([batch]))
        metrics = SCHEMA.names[1:]
        field_tuple = "tuple(" + ", ".join(metrics) + ")"
        columns = ", ".join(SCHEMA.names)
        picked = ", ".join(f"tupleElement(picked, {i})" for i in range(1, len(metrics) + 1))
        client.command(f"""
            INSERT INTO {fact} ({columns})
            SELECT trip_id, {picked} FROM (
                SELECT trip_id, min({field_tuple}) AS picked FROM {stage} GROUP BY trip_id
            )
        """)
        detail = client.query(f"""SELECT count(), countIf(pickup_zone = 0),
            sum(ifNull(amount_cents, 0)), count(amount_cents), sum(ifNull(duration, 0)),
            count(duration) FROM {fact}""").result_rows[0]
        aggregate = client.query(f"""SELECT sum(trips), sumIf(trips, pickup_zone=0),
            sum(total_cents), sum(known_total), sum(duration_seconds), sum(known_duration)
            FROM {database}.agg_zone_hour""").result_rows[0]
        flow = client.query(f"SELECT sum(trips) FROM {database}.agg_od_day").result_rows[0][0]
        if not detail[0] or detail != aggregate or flow != detail[0]:
            raise ValueError("La revisión no pasó la conciliación de hechos y agregados.")
        observed = sum(entry["accepted_rows"] for entry in manifest["files"])
        if observed != client.query(f"SELECT count() FROM {stage}").result_rows[0][0]:
            raise ValueError("El conteo de staging difiere del manifiesto.")
        manifest.update(lot=database, rows=detail[0], unknown_pickup=detail[1],
                        duplicate_rows=observed - detail[0])
        client.insert(f"{database}.dataset_metadata", [[json.dumps(manifest, ensure_ascii=False)]],
                      column_names=["payload"])
        client.command(f"DROP TABLE {stage}")
    print(f"{database}: {manifest['rows']:,} viajes conciliados", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Extrae o carga un lote de Pulso Chicago.")
    commands = parser.add_subparsers(dest="command", required=True)
    extraction = commands.add_parser("extract")
    extraction.add_argument("--start", type=date.fromisoformat, required=True)
    extraction.add_argument("--end", type=date.fromisoformat, required=True)
    extraction.add_argument("--page-size", type=int, default=50_000, choices=(10_000, 25_000, 50_000))
    extraction.add_argument("--workers", type=int, default=4, choices=range(1, 9), metavar="1..8")
    loading = commands.add_parser("load")
    loading.add_argument("--database", required=True)
    for command in (extraction, loading):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "extract":
        if not timedelta(0) <= args.end - args.start <= timedelta(days=30):
            parser.error("El rango debe contener de 1 a 31 días.")
        extract(args.start, args.end, args.output, args.page_size, args.workers)
    else:
        load(args.output, args.database)


if __name__ == "__main__":
    main()
