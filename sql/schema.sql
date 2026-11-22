CREATE TABLE {database}.fact_trips (
  trip_id String,
  trip_date Date,
  trip_hour UInt8,
  pickup_zone UInt8,
  dropoff_zone UInt8,
  duration Nullable(UInt32),
  miles Nullable(Float32),
  fare_cents Nullable(Int64),
  amount_cents Nullable(Int64)
) ENGINE = MergeTree PARTITION BY toYYYYMM(trip_date)
ORDER BY (trip_date, pickup_zone, trip_hour, trip_id);

CREATE TABLE {database}.agg_zone_hour (
  trip_date Date,
  trip_hour UInt8,
  pickup_zone UInt8,
  trips UInt64,
  total_cents Int64,
  known_total UInt64,
  duration_seconds UInt64,
  known_duration UInt64
) ENGINE = SummingMergeTree PARTITION BY toYYYYMM(trip_date)
ORDER BY (trip_date, pickup_zone, trip_hour);

CREATE MATERIALIZED VIEW {database}.mv_zone_hour TO {database}.agg_zone_hour AS
SELECT trip_date, trip_hour, pickup_zone, count() AS trips,
  sum(ifNull(amount_cents, 0)) AS total_cents, count(amount_cents) AS known_total,
  sum(ifNull(duration, 0)) AS duration_seconds, count(duration) AS known_duration
FROM {database}.fact_trips GROUP BY trip_date, trip_hour, pickup_zone;

CREATE TABLE {database}.agg_od_day (
  trip_date Date,
  pickup_zone UInt8,
  dropoff_zone UInt8,
  trips UInt64
) ENGINE = SummingMergeTree PARTITION BY toYYYYMM(trip_date)
ORDER BY (trip_date, pickup_zone, dropoff_zone);

CREATE MATERIALIZED VIEW {database}.mv_od_day TO {database}.agg_od_day AS
SELECT trip_date, pickup_zone, dropoff_zone, count() AS trips
FROM {database}.fact_trips GROUP BY trip_date, pickup_zone, dropoff_zone;

CREATE TABLE {database}.dataset_metadata (payload String) ENGINE = MergeTree ORDER BY tuple();
