# Rendimiento OLAP · Pulso Chicago

Lote `pulso_202511_demo` de 3,676,279 viajes. ClickHouse `25.8.33.6`.
Consultas del 2025-11-03 al 2025-11-16. Zona 8 para horas y destinos.
Se alternaron variantes, con tres calentamientos y 30 ejecuciones medidas por variante.
Caché de resultados desactivada. Máximo cuatro hilos por consulta. Duración del motor, en caliente.
Las consultas de cada par devolvieron las mismas filas y los mismos valores.

| Consulta | Variante | p50 (ms) | p95 (ms) | Filas leídas (mediana) | Bytes leídos (mediana) |
| --- | --- | ---: | ---: | ---: | ---: |
| mapa | detalle | 8 | 19 | 3,676,279 | 11,028,837 |
| mapa | agregado | 4 | 4 | 26,141 | 287,551 |
| horas | detalle | 7 | 9 | 1,433,600 | 4,519,130 |
| horas | agregado | 4 | 5 | 26,141 | 313,692 |
| destinos | detalle | 7 | 12 | 1,433,600 | 4,519,130 |
| destinos | agregado | 4 | 6 | 65,521 | 786,252 |
