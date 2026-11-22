import json
import sys
from urllib.parse import urlencode
from urllib.request import urlopen


def fetch(url):
    with urlopen(url, timeout=25) as response:
        return response.read()


def smoke(base):
    if b"Pulso Chicago" not in fetch(base + "/"):
        raise RuntimeError("No se encontró el dashboard.")
    metadata = json.loads(fetch(base + "/api/metadata"))
    if metadata["rows"] <= 0:
        raise RuntimeError("El lote publicado está vacío.")
    params = urlencode({"start": metadata["start"], "end": metadata["end"]})
    overview = json.loads(fetch(base + "/api/overview?" + params))
    if overview["summary"]["journeys"] != metadata["rows"]:
        raise RuntimeError("El resumen público no coincide con el lote declarado.")
    print(f"Lote {metadata['lot']} verificado con {metadata['rows']} viajes.")


if __name__ == "__main__":
    smoke(sys.argv[1].rstrip("/"))
