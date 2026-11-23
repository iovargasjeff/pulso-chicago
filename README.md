# Pulso Chicago

Explorador OLAP de viajes por aplicación en Chicago. Permite ir de la demanda de toda la ciudad al detalle por área comunitaria, comparar dos periodos consecutivos de siete días y seguir los flujos entre zonas. La aplicación usa React, ECharts, FastAPI y ClickHouse.

## Ejecutar localmente

Requiere Python 3.13, Node.js 22 y Docker con Compose. Ejecuta desde la raíz del repositorio en PowerShell.

```powershell
docker compose up -d --wait
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
$env:RUN_CLICKHOUSE_TESTS = '1'
.venv/Scripts/python -m pytest -q
```

Descarga un corte histórico y cárgalo en un esquema nuevo. Para reproducir el corte de dos semanas ejecuta lo siguiente.

```powershell
.venv/Scripts/python -m ingest.pipeline extract --start 2025-11-03 --end 2025-11-16 --output data/demo
.venv/Scripts/python -m ingest.pipeline load --output data/demo --database pulso_202511_demo
$env:PULSO_DATABASE = 'pulso_202511_demo'
.venv/Scripts/python -m uvicorn api.main:app --port 8080
```

Abre [el dashboard local](http://127.0.0.1:8080/) o [la documentación de la API](http://127.0.0.1:8080/docs). Para una prueba rápida usa un día en ambos parámetros de fecha. El corte completo previsto va del 1 al 30 de noviembre de 2025. La extracción retoma días ya guardados si se conserva el manifiesto diario y coincide su checksum. El token opcional de Socrata entra por `SOCRATA_APP_TOKEN`.

## Modelado y medición

El hecho usa una fila por `trip_id`. Las vistas materializadas mantienen agregados por fecha, hora y zona de origen, y por fecha y par origen–destino. Los promedios se calculan desde sumas y conteos de valores presentes. El código de zona 0 representa zonas sin reportar. Los importes se normalizan a centavos. Se conservan la fecha y hora calendario de Chicago que publica el proveedor. El cambio de horario agrupa las horas locales repetidas. La metodología del panel muestra el lote activo y los descartes.

```powershell
.venv/Scripts/python -m benchmark.run --database pulso_202511_demo --start 2025-11-03 --end 2025-11-16 --zone 8
```

El [informe del corte validado](benchmark/results/resumen.md) y sus [mediciones individuales](benchmark/results/mediciones.csv) documentan 3.676.279 viajes y 180 consultas medidas en ClickHouse local. La herramienta comprueba igualdad de resultados antes de informar p50, p95, filas y bytes por consulta. Consulta `data/benchmark/mediciones.csv` y `data/benchmark/resumen.md`. Usa un usuario con lectura de `system.query_log` y añade `--cluster-logs` si las consultas se reparten por las réplicas de ClickHouse Cloud.

## Despliegue público en Dokploy

[Explorar Pulso Chicago](https://pulso-chicago-6c7ff4-13-140-40-36.sslip.io/). El despliegue utiliza Docker Compose en un VPS de Contabo.

`compose.dokploy.yaml` mantiene ClickHouse y la carga inicial en una red interna. La carga crea el esquema desde la fuente pública y prepara el usuario SQL de solo lectura. El dashboard empieza a servir después de conciliar el lote. Los volúmenes conservan ClickHouse y los archivos Parquet entre despliegues. En Dokploy se configuran los secretos `PULSO_LOADER_PASSWORD` y `PULSO_READER_PASSWORD` con claves hexadecimales independientes.

GitHub Actions valida el código y las consultas. Al pasar la validación en `main`, solicita un despliegue mediante el webhook de Dokploy, guardado como secreto `PULSO_DOKPLOY_WEBHOOK`. Solo el servicio `dashboard` recibe el tráfico HTTPS de Traefik.

## Ruta alternativa por CLI en Google Cloud

1. Usa un proyecto dedicado de Google Cloud con facturación y habilita Cloud Run, Cloud Build, Artifact Registry y Secret Manager. Crea ClickHouse Cloud sobre Google Cloud en `us-central1` y verifica que el servicio de Cloud Run podrá llegar al endpoint TLS. Para restringir el origen por IP se necesita configurar salida estática.
2. Conserva una copia privada de los Parquet y el manifiesto con `gcloud storage cp --recursive data/demo gs://TU_BUCKET/lotes/`. Carga el corte en ClickHouse Cloud con el mismo comando y las variables `CLICKHOUSE_HOST`, `CLICKHOUSE_LOADER_USER`, `CLICKHOUSE_LOADER_PASSWORD` e `CLICKHOUSE_SECURE=true`. El cargador necesita permisos para crear el esquema, insertar y validar. Crea un usuario de lectura con SELECT sobre `agg_zone_hour`, `agg_od_day` y `dataset_metadata` del esquema publicado. Guarda las credenciales de lectura en los secretos `pulso-clickhouse-user` y `pulso-clickhouse-password`, y concede acceso a esos dos secretos a la identidad de ejecución de Cloud Run.
3. Desde la raíz, publica con el script. El proyecto debe permitir servicios Cloud Run públicos.

```powershell
./infra/deploy.ps1 -Project TU_PROYECTO -ClickHouseHost HOST_CLICKHOUSE -Database pulso_202511_demo -RuntimeAccount CUENTA_RUNTIME
```

4. Conecta el repositorio en Cloud Build y crea un disparador de push exclusivo para `^main$` que use `cloudbuild.yaml`. Asigna al disparador una identidad con permisos para escribir en `cloud-run-source-deploy`, registrar logs, desplegar revisiones y actuar como la identidad de ejecución de Cloud Run. Conserva las credenciales del motor en Secret Manager. El pipeline prueba normalización, construye, publica y fija la imagen por digest. Luego valida la revisión candidata y le asigna tráfico. GitHub Actions valida adicionalmente los endpoints contra ClickHouse antes de fusionar.
   Después de vincular el repositorio desde Cloud Build, también puedes crear el disparador de GitHub desde PowerShell.

   ```powershell
   ./infra/trigger.ps1 -Project TU_PROYECTO -BuildAccount CUENTA_BUILD -RepoOwner USUARIO_GITHUB
   ```

5. Guarda la URL inicial y la URL de la ejecución automática. Una revisión previa puede volver a recibir el tráfico con `gcloud run services update-traffic pulso-chicago --region us-central1 --to-revisions REVISION=100`.

La cuenta de ejecución guarda el lote activo mediante `PULSO_DATABASE`. Para actualizar datos, carga y concilia un esquema nuevo, concede los tres permisos SELECT al lector y actualiza la revisión con el nuevo identificador. Mantén el esquema anterior durante la ventana de reversión.

[Despliegue desde código fuente](https://docs.cloud.google.com/run/docs/deploying-source-code) · [Disparadores de Cloud Build](https://docs.cloud.google.com/build/docs/automating-builds/create-manage-triggers) · [Secretos en Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## Material de entrega

Consulta los [enfoques de artículos](docs/publicaciones.md) y la [plantilla de enlaces](Plantilla-ENLACES.md).

## Fuentes

[Viajes reportados por plataformas](https://data.cityofchicago.org/d/6dvr-xwnh) · [Límites de áreas comunitarias](https://data.cityofchicago.org/d/igwz-8jzy). Responsable de la publicación de datos: City of Chicago.
