import os
import re

import clickhouse_connect


def database_name(value: str) -> str:
    if not re.fullmatch(r"pulso_[a-z0-9_]{1,45}", value):
        raise ValueError("Usa un identificador como pulso_202511.")
    return value


def connect(database=None, *, loading=False):
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    secure = os.getenv("CLICKHOUSE_SECURE", "false" if host == "localhost" else "true") == "true"
    prefix = "CLICKHOUSE_LOADER" if loading else "CLICKHOUSE"
    return clickhouse_connect.get_client(
        host=host,
        port=int(os.getenv("CLICKHOUSE_PORT", "8443" if secure else "8123")),
        secure=secure,
        username=os.getenv(f"{prefix}_USER", "pulso"),
        password=os.getenv(f"{prefix}_PASSWORD", "pulso-local"),
        database=database or "default",
        connect_timeout=5,
        send_receive_timeout=120 if loading else 10,
        autogenerate_session_id=False,
    )
