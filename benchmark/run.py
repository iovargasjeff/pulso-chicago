import argparse
import csv
import json
import math
import statistics
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

from clickhouse_connect.driver.exceptions import ClickHouseError

from api.db import connect, database_name

WINDOW = "trip_date BETWEEN {start:Date} AND {end:Date}"
QUERIES = {
    "mapa": (
        f"SELECT pickup_zone, count() FROM fact_trips WHERE {WINDOW} GROUP BY pickup_zone ORDER BY pickup_zone",
        f"SELECT pickup_zone, sum(trips) FROM agg_zone_hour WHERE {WINDOW} GROUP BY pickup_zone ORDER BY pickup_zone",
    ),
    "horas": (
        f"""SELECT toDayOfWeek(trip_date), trip_hour, count() FROM fact_trips
            WHERE {WINDOW} AND pickup_zone = {{zone:UInt8}} GROUP BY 1, 2 ORDER BY 1, 2""",
        f"""SELECT toDayOfWeek(trip_date), trip_hour, sum(trips) FROM agg_zone_hour
            WHERE {WINDOW} AND pickup_zone = {{zone:UInt8}} GROUP BY 1, 2 ORDER BY 1, 2""",
    ),
    "destinos": (
        f"""SELECT dropoff_zone, count() AS trips FROM fact_trips WHERE {WINDOW} AND pickup_zone = {{zone:UInt8}}
            GROUP BY dropoff_zone ORDER BY trips DESC, dropoff_zone LIMIT 10""",
        f"""SELECT dropoff_zone, sum(trips) AS journeys FROM agg_od_day WHERE {WINDOW} AND pickup_zone = {{zone:UInt8}}
            GROUP BY dropoff_zone ORDER BY journeys DESC, dropoff_zone LIMIT 10""",
    ),
}


def collect_log(client, marker, ids, cluster):
    source = "clusterAllReplicas(default, system.query_log)" if cluster else "system.query_log"
    for _ in range(12):
        logs = client.query(
            f"""SELECT query_id, query_duration_ms, read_rows, read_bytes FROM {source}
                WHERE type = 'QueryFinish' AND log_comment = {{marker:String}}""",
            parameters={"marker": marker},
        ).result_rows
        indexed = {row[0]: row[1:] for row in logs}
        if ids <= indexed.keys():
            return indexed
        time.sleep(3)
    raise RuntimeError(f"Faltan {len(ids - indexed.keys())} mediciones en system.query_log.")


def percentile(values, fraction):
    return sorted(values)[math.ceil(len(values) * fraction) - 1]


def run(database, start, end, zone, iterations, cluster, output):
    marker = "pulso_" + uuid4().hex
    settings = {"use_query_cache": 0, "log_queries": 1, "log_comment": marker, "max_threads": 4}
    params = {"start": start, "end": end, "zone": zone}
    executions = []
    with connect(database_name(database), loading=True) as client:
        metadata = json.loads(client.query("SELECT payload FROM dataset_metadata LIMIT 1").first_row[0])
        version = client.query("SELECT version()").first_row[0]
        for name, statements in QUERIES.items():
            for i in range(iterations + 3):
                order = (0, 1) if i % 2 == 0 else (1, 0)
                answers = {}
                for variant in order:
                    result = client.query(statements[variant], parameters=params, settings=settings)
                    answers[variant] = result.result_rows
                    if i >= 3:
                        executions.append((name, ("detalle", "agregado")[variant], result.query_id))
                if answers[0] != answers[1]:
                    raise ValueError(f"Resultados OLAP diferentes para {name}.")
        try:
            client.command("SYSTEM FLUSH LOGS")
        except ClickHouseError:
            pass
        logs = collect_log(client, marker, {item[2] for item in executions}, cluster)

    output.mkdir(parents=True, exist_ok=True)
    with (output / "mediciones.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["consulta", "variante", "query_id", "duracion_ms", "filas_leidas", "bytes_leidos"])
        writer.writerows((*item, *logs[item[2]]) for item in executions)
    report = [
        "# Rendimiento OLAP · Pulso Chicago", "",
        f"Lote `{database}` de {metadata['rows']:,} viajes. ClickHouse `{version}`.",
        f"Consultas del {start} al {end}. Zona {zone} para horas y destinos.",
        f"Se alternaron variantes, con tres calentamientos y {iterations} ejecuciones medidas por variante.",
        "Caché de resultados desactivada. Máximo cuatro hilos por consulta. Duración del motor, en caliente.",
        "Las consultas de cada par devolvieron las mismas filas y los mismos valores.", "",
        "| Consulta | Variante | p50 (ms) | p95 (ms) | Filas leídas (mediana) | Bytes leídos (mediana) |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    metrics = []
    for name in QUERIES:
        for variant in ("detalle", "agregado"):
            matching = [logs[query_id] for query, kind, query_id in executions if query == name and kind == variant]
            elapsed, rows, bytes_read = zip(*matching)
            metrics.append(dict(query=name, variant=variant, p50_ms=statistics.median(elapsed),
                                p95_ms=percentile(elapsed, .95), read_rows=statistics.median(rows),
                                read_bytes=statistics.median(bytes_read)))
            report.append(
                f"| {name} | {variant} | {statistics.median(elapsed):g} | {percentile(elapsed, .95)} | "
                f"{statistics.median(rows):,.0f} | {statistics.median(bytes_read):,.0f} |"
            )
    (output / "resumen.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    report_data = dict(lot=database, rows=metadata["rows"], version=version, start=str(start),
                       end=str(end), zone=zone, iterations=iterations, metrics=metrics)
    (output / "benchmark.json").write_text(json.dumps(report_data, indent=2) + "\n", encoding="utf-8")
    print("\n".join(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compara consultas sobre hechos y agregados.")
    parser.add_argument("--database", required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--zone", type=int, default=8, choices=range(1, 78), metavar="1..77")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--cluster-logs", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/benchmark"))
    args = parser.parse_args()
    if args.iterations < 1 or args.end < args.start:
        parser.error("Indica un rango válido y al menos una iteración.")
    run(args.database, args.start, args.end, args.zone, args.iterations, args.cluster_logs, args.output)
