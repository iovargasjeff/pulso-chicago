# Artículos y video de Pulso Chicago

## Artículo de datos

**Título de trabajo:** Cómo construí un lote reproducible de viajes de Chicago para OLAP

Explicar la fuente 6dvr-xwnh y por qué se fijaron fechas históricas. Mostrar la extracción por ventanas diarias, la paginación por fecha e ID y los reintentos. Incluir el comando `python -m ingest.pipeline extract` y un manifiesto real. Explicar las zonas sin código, los valores faltantes, el redondeo de origen y cómo se evita publicar un lote incompleto.

## Artículo de modelado

**Título de trabajo:** Medir qué cambia al preagregar la demanda de viajes en ClickHouse

Partir de una consulta de viajes por zona. Mostrar el grano del hecho, las claves de orden y cómo una vista materializada alimenta `agg_zone_hour`. Ejecutar ambos agrupamientos sobre el mismo corte. Reportar p50, p95, filas y bytes junto con la configuración del experimento y los límites de trasladar resultados locales a producción.

## Artículo de producto

**Título de trabajo:** Un dashboard OLAP que baja de toda Chicago a su hora pico

Mostrar el mapa, el filtro de zona y una comparación entre las dos semanas del lote. Incluir la llamada a `/api/demand`, la captura de la zona elegida y el resultado observado. Explicar el denominador en los destinos y el tratamiento de las áreas sin código.

## Artículo de despliegue

**Título de trabajo:** Publicar una app OLAP con gcloud y Cloud Build

Explicar el contenedor único, el script de despliegue, el usuario de solo lectura, la configuración de Secret Manager y la promoción de una revisión tras una prueba de humo. Añadir los enlaces a la demo y a la ejecución de Cloud Build cuando estén verificados.

## Entrega

Cada integrante escogerá el frente que implementó y redactará desde su propia cuenta. Usar permalinks del repositorio para código y mediciones. Completar la plantilla de enlaces después de publicar. La descripción del video debe enlazar el repositorio, la demo pública y los artículos ya visibles.
