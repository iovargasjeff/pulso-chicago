import os
import re
from datetime import date
from pathlib import Path

from api.db import connect, database_name
from ingest.pipeline import extract, load


def seeded(client, database):
    if not client.query(f"EXISTS TABLE {database}.dataset_metadata").first_row[0]:
        return False
    return client.query(f"SELECT count() FROM {database}.dataset_metadata").first_row[0] == 1


def main():
    database = database_name(os.environ["PULSO_DATABASE"])
    password = os.environ["CLICKHOUSE_PASSWORD"]
    if not re.fullmatch(r"[0-9a-f]{48,128}", password):
        raise ValueError("PULSO_READER_PASSWORD debe ser una clave aleatoria hexadecimal.")
    snapshot = Path("/snapshots/2025-11-03_2025-11-16")
    with connect(loading=True) as loader:
        if not seeded(loader, database):
            extract(date(2025, 11, 3), date(2025, 11, 16), snapshot, 50_000, 4)
            # The dedicated database can only have an incomplete load without its verified manifest.
            loader.command(f"DROP DATABASE IF EXISTS {database} SYNC")
            load(snapshot, database)

        loader.command(f"CREATE USER IF NOT EXISTS pulso_reader IDENTIFIED WITH sha256_password BY '{password}'")
        loader.command(f"ALTER USER pulso_reader IDENTIFIED WITH sha256_password BY '{password}'")
        for table in ("agg_zone_hour", "agg_od_day", "dataset_metadata"):
            loader.command(f"GRANT SELECT ON {database}.{table} TO pulso_reader")
        print(f"{database} disponible para el dashboard.", flush=True)


if __name__ == "__main__":
    main()
