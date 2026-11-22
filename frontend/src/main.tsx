import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import * as echarts from 'echarts/core';
import { HeatmapChart, LineChart, MapChart } from 'echarts/charts';
import { GeoComponent, GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
import './style.css';

echarts.use([HeatmapChart, LineChart, MapChart, GeoComponent, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer]);

type Metadata = {
  start: string; end: string; rows: number; source_rows: number; discarded_rows: number;
  duplicate_rows: number; unknown_pickup: number; lot: string; assembled_at: string;
};
type Overview = {
  summary: { journeys: number; average_total: number | null; average_minutes: number | null };
  zones: { zone: number; journeys: number }[];
  timeline: { day: string; journeys: number }[];
};
type Benchmark = { lot: string; rows: number; version: string; iterations: number; metrics: {
  query: string; variant: string; p50_ms: number; p95_ms: number; read_rows: number; read_bytes: number;
}[] };
type Demand = { weekday: number; hour: number; journeys: number };
type Flow = { zone: number; journeys: number; share: number };
type Geo = { features: { properties: { code: number; name: string } }[] };
const weekdays = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'];
const numbers = new Intl.NumberFormat('es-PE');
const money = new Intl.NumberFormat('es-PE', { style: 'currency', currency: 'USD' });
const dates = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const fmt = (n: number) => numbers.format(n);
const dayLabel = (day: string) => dates.format(new Date(day + 'T12:00:00Z'));
const isoAdd = (day: string, days: number) => {
  const value = new Date(day + 'T00:00:00Z');
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
};

async function get<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error('No se pudo consultar el lote. Inténtalo de nuevo.');
  return response.json();
}

function Chart({ option, label, select, className = '' }: {
  option: EChartsOption; label: string; select?: (name: string, value: unknown) => void; className?: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const callback = useRef(select);
  callback.current = select;

  useEffect(() => {
    if (!element.current) return;
    const instance = echarts.init(element.current);
    chart.current = instance;
    instance.on('click', event => callback.current?.(event.name, event.value));
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); instance.dispose(); chart.current = null; };
  }, []);
  useEffect(() => { chart.current?.setOption(option, true); }, [option]);

  return <div ref={element} className={'chart ' + className} role="img" aria-label={label} />;
}

function compareWeeks(timeline: Overview['timeline'], end: string) {
  const counts = new Map(timeline.map(entry => [entry.day, entry.journeys]));
  const week = (offset: number) => Array.from({ length: 7 }, (_, i) => isoAdd(end, offset - i));
  if (week(0).concat(week(-7)).some(day => !counts.has(day))) return null;
  const total = (offset: number) => week(offset).reduce((sum, day) => sum + (counts.get(day) ?? 0), 0);
  const previous = total(-7);
  return previous ? { previous, current: total(0), percent: 100 * (total(0) - previous) / previous } : null;
}

function App() {
  const [meta, setMeta] = useState<Metadata>();
  const [benchmark, setBenchmark] = useState<Benchmark>();
  const [geo, setGeo] = useState<Geo>();
  const [overview, setOverview] = useState<Overview>();
  const [demand, setDemand] = useState<Demand[]>([]);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [zone, setZone] = useState('');
  const [hour, setHour] = useState('');
  const [error, setError] = useState('');
  const [pending, setPending] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    Promise.all([
      get<Metadata>('/api/metadata', controller.signal),
      get<Geo>('/community-areas.geojson', controller.signal)
    ]).then(([dataset, geometry]) => {
      echarts.registerMap('chicago', geometry as unknown as Parameters<typeof echarts.registerMap>[1]);
      setGeo(geometry); setMeta(dataset); setStart(dataset.start); setEnd(dataset.end);
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    const controller = new AbortController();
    get<Benchmark>('/benchmark.json', controller.signal).then(setBenchmark).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!start || !end || start > end) return;
    const controller = new AbortController();
    const filters = new URLSearchParams({ start, end });
    if (zone !== '') filters.set('zone', zone);
    const hourly = new URLSearchParams(filters);
    if (hour !== '') hourly.set('hour', hour);
    setPending(true);
    Promise.all([
      get<Overview>('/api/overview?' + filters, controller.signal),
      get<Demand[]>('/api/demand?' + hourly, controller.signal),
      get<Flow[]>('/api/flows?' + filters, controller.signal)
    ]).then(([summary, hours, routes]) => {
      setOverview(summary); setDemand(hours); setFlows(routes); setError('');
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setPending(false); });
    return () => controller.abort();
  }, [start, end, zone, hour, retry]);

  const areas = geo?.features.map(feature => feature.properties).sort((a, b) => a.name.localeCompare(b.name)) ?? [];
  const nameOf = (code: number) => code === 0 ? 'Sin zona reportada' : areas.find(area => area.code === code)?.name ?? String(code);
  const activeZone = zone === '' ? 'Toda la ciudad' : nameOf(Number(zone));
  const total = overview?.summary;
  const weekly = overview && compareWeeks(overview.timeline, end);
  const peak = demand.reduce<Demand | undefined>((best, entry) => !best || entry.journeys > best.journeys ? entry : best, undefined);
  const from = meta ? dayLabel(meta.start) + ' – ' + dayLabel(meta.end) + ', ' + meta.end.slice(0, 4) : 'Cargando cobertura';
  const unknown = overview?.zones.find(item => item.zone === 0)?.journeys ?? 0;
  const mapData = (overview?.zones ?? []).filter(item => item.zone).map(item => ({ name: nameOf(item.zone), value: item.journeys, selected: zone === String(item.zone) }));
  const mapMax = Math.max(1, ...mapData.map(item => item.value));
  const hourlyCount = new Map(demand.map(item => [item.weekday + ':' + item.hour, item.journeys]));
  const heatData = Array.from({length: 7}, (_, day) => Array.from({length: 24}, (_, h) =>
    hour !== '' && h !== Number(hour) ? [h, day, '-'] : [h, day, hourlyCount.get((day + 1) + ':' + h) ?? 0]
  )).flat();
  const heatLabel = peak ? weekdays[peak.weekday - 1] + ' · ' + String(peak.hour).padStart(2, '0') + ':00' : 'Sin viajes';
  const tooltip = { trigger: 'item' as const, renderMode: 'richText' as const, confine: true };
  const mapOption: EChartsOption = {
    tooltip,
    visualMap: { min: 0, max: mapMax, left: 10, bottom: 10, calculable: false, text: ['Más viajes', 'Menos'], inRange: { color: ['#d2efe7', '#65c9b6', '#15837a', '#084c51'] } },
    series: [{ type: 'map', map: 'chicago', roam: false, data: mapData, layoutCenter: ['53%', '48%'], layoutSize: '92%',
      itemStyle: { borderColor: '#f1f5f2', borderWidth: 1, areaColor: '#dbe6e2' },
      emphasis: { itemStyle: { areaColor: '#e5a15d' }, label: { show: false } },
      select: { label: { show: false }, itemStyle: { areaColor: '#e5a15d' } }, selectedMode: 'single',
    }]
  };
  const heatOption: EChartsOption = {
    tooltip: { ...tooltip, formatter: (info) => {
      if (Array.isArray(info) || !Array.isArray(info.value)) return '';
      const [h, d, count] = info.value.map(Number);
      if (![h, d, count].every(Number.isFinite)) return '';
      return weekdays[d] + ' · ' + String(h).padStart(2, '0') + ':00\n' + fmt(count) + ' viajes';
    }},
    grid: { top: 12, left: 45, right: 15, bottom: 50 },
    xAxis: { type: 'category', data: Array.from({length: 24}, (_, i) => String(i).padStart(2, '0')), axisLabel: { interval: 3 }, axisTick: { show: false } },
    yAxis: { type: 'category', data: weekdays, inverse: true, axisTick: { show: false } },
    visualMap: { min: 0, max: Math.max(1, peak?.journeys ?? 0), bottom: 0, left: 'center', orient: 'horizontal', itemHeight: 92,
      inRange: { color: ['#edf4f1', '#9ddbd0', '#1e9b8b', '#075452'] } },
    series: [{ type: 'heatmap', data: heatData, itemStyle: { borderColor: '#fff', borderWidth: 2 } }]
  };
  const timelineOption: EChartsOption = {
    tooltip: { ...tooltip, trigger: 'axis' }, grid: { top: 12, left: 60, right: 22, bottom: 36 },
    xAxis: { type: 'category', data: overview?.timeline.map(item => dayLabel(item.day)), axisLabel: { hideOverlap: true } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#e6efed' } }, axisLabel: { formatter: (n: number) => fmt(n) } },
    series: [{ type: 'line', data: overview?.timeline.map(item => item.journeys), symbolSize: 7,
      itemStyle: { color: '#0d887b' }, lineStyle: { width: 3 }, areaStyle: { color: '#d7eee9' } }]
  };
  return <>
    <header className="top"><div className="shell top-inner">
      <a className="brand" href="#"><span className="brand-icon">▥</span> Pulso Chicago</a>
      <nav><a href="#explorar">Explorar</a><a href="#metodo">Metodología</a></nav>
    </div></header>
    <main>
      <section className="hero"><div className="shell hero-inner">
        <div><p className="eyebrow">MOVILIDAD URBANA / CHICAGO</p><h1>El ritmo de<br />la ciudad<span>.</span></h1>
        <p className="intro">Descubre dónde y cuándo se concentran los viajes por aplicación en Chicago.</p></div>
        <div className="hero-stats"><span>CORTE HISTÓRICO</span><strong>{meta ? fmt(meta.rows) : '—'}</strong>
        <span>viajes validados</span><div className="hero-date">{from}</div></div>
      </div></section>
      <div className="shell workspace" id="explorar">
        {error && <div className="notice" role="alert">{error} <button onClick={() => setRetry(retry + 1)}>Reintentar</button></div>}
        {!meta && !error && <p role="status" className="notice">Cargando el panel y la cobertura del lote…</p>}
        {meta && <>
          <section className="control-panel" aria-label="Filtros de exploración">
            <div><p className="eyebrow">EXPLORADOR DE DEMANDA</p><h2>{activeZone}</h2></div>
            <div className="filters">
              <label>Desde<input type="date" value={start} min={meta.start} max={end || meta.end} onChange={event => setStart(event.target.value)} /></label>
              <label>Hasta<input type="date" value={end} min={start || meta.start} max={meta.end} onChange={event => setEnd(event.target.value)} /></label>
              <label>Zona de origen<select aria-label="Zona de origen" value={zone} onChange={event => setZone(event.target.value)}><option value="">Toda la ciudad</option>
                {areas.map(area => <option key={area.code} value={area.code}>{area.name}</option>)}<option value="0">Sin zona reportada</option></select></label>
              <button className="reset" onClick={() => { setZone(''); setHour(''); setStart(meta.start); setEnd(meta.end); }}>Restablecer</button>
            </div>
            {(start === '' || end === '' || start > end) && <p role="alert">Selecciona un rango de fechas válido.</p>}
          </section>
          <p className="sr-only" role="status">{pending ? 'Actualizando datos' : 'Datos actualizados'}</p>
          <div className="metrics" aria-busy={pending}>
            <article><span>Viajes observados</span><strong>{total ? fmt(total.journeys) : '—'}</strong><small>En la selección actual</small></article>
            <article><span>Monto total medio</span><strong>{total?.average_total != null ? money.format(total.average_total) : '—'}</strong><small>Por viaje con monto reportado</small></article>
            <article><span>Duración media</span><strong>{total?.average_minutes != null ? fmt(total.average_minutes) : '—'}{total?.average_minutes != null && <em> min</em>}</strong><small>Por viaje con duración reportada</small></article>
            <article><span>Últimos 7 días vs. 7 previos</span><strong>{weekly ? (weekly.percent > 0 ? '+' : '') + fmt(Math.round(weekly.percent * 10) / 10) + '%' : '—'}</strong><small>{weekly ? fmt(weekly.current) + ' frente a ' + fmt(weekly.previous) + ' viajes' : 'Requiere 14 días con viajes'}</small></article>
          </div>
          <div className="grid" aria-busy={pending}>
            <article className="card">
              <div className="card-head"><div><h3>Orígenes de los viajes</h3><p>Selecciona un área para explorar su demanda.</p></div><span className="chip">77 áreas</span></div>
              <Chart option={mapOption} label="Mapa de viajes por área. El selector Zona de origen ofrece los mismos filtros." className="map" select={name => {
                const area = areas.find(item => item.name === name);
                if (area) setZone(String(area.code));
              }} />
              <p className="footnote">{fmt(unknown)} viajes del rango no tienen zona de origen reportada.</p>
            </article>
            <article className="card">
              <div className="card-head"><div><h3>Horas de mayor demanda</h3><p>{activeZone} · Hora local de Chicago</p></div></div>
              <div className="peak"><strong>{heatLabel}</strong><span>{peak ? fmt(peak.journeys) + ' viajes' : 'Sin resultados para el filtro'}</span>
                <label>Hora<select aria-label="Hora" value={hour} onChange={event => setHour(event.target.value)}><option value="">Todas</option>{Array.from({length:24}, (_, i) => <option key={i} value={i}>{String(i).padStart(2,'0')}:00</option>)}</select></label>
              </div>
              <Chart option={heatOption} label="Mapa de calor de viajes por día de la semana y franja horaria" className="heat" />
            </article>
            <article className="card">
              <div className="card-head"><div><h3>Viajes por día</h3><p>Evolución de la demanda en la zona seleccionada.</p></div></div>
              {overview && overview.timeline.length === 0 && <p className="notice">Sin viajes para la selección.</p>}
              <Chart option={timelineOption} label="Serie de viajes observados por día" />
            </article>
            <article className="card">
              <div className="card-head"><div><h3>Destinos más frecuentes</h3><p>Proporción sobre todos los viajes del origen seleccionado.</p></div></div>
              <ol className="routes">{flows.map(item => <li key={item.zone}><div><span>{nameOf(item.zone)}</span><strong>{fmt(item.share)}%</strong></div><div className="track"><span style={{ width: item.share + '%' }} /></div><small>{fmt(item.journeys)} viajes</small></li>)}</ol>
              {flows.length === 0 && <p className="notice">Sin destinos para la selección.</p>}
            </article>
          </div>
          <section className="method card" id="metodo"><div><p className="eyebrow">DATOS Y MÉTODO</p><h2>Cómo se construyó el análisis</h2></div>
            <p>Este lote contiene viajes históricos reportados por aplicaciones. Los horarios de la fuente se redondean a intervalos de 15 minutos y las tarifas a múltiplos de USD 2.50. El monto total incluye los cargos reportados. Las zonas sin código se cuentan aparte.</p>
            <dl><div><dt>Lote</dt><dd>{meta.lot}</dd></div><div><dt>Filas de origen</dt><dd>{fmt(meta.source_rows)}</dd></div><div><dt>Descartes en la extracción</dt><dd>{fmt(meta.discarded_rows)}</dd></div><div><dt>Duplicados entre archivos</dt><dd>{fmt(meta.duplicate_rows)}</dd></div></dl>
            <a href="https://data.cityofchicago.org/d/6dvr-xwnh">Fuente municipal de viajes ↗</a>
            {benchmark && <div className="benchmark">
              <h3>Detalle frente a preagregados</h3>
              <p>ClickHouse {benchmark.version} · {fmt(benchmark.rows)} viajes · {benchmark.iterations} mediciones por variante.
                {benchmark.lot !== meta.lot && ' La prueba se ejecutó en un lote de referencia.'}</p>
              <div className="table-scroll"><table>
                <thead><tr><th>Consulta</th><th>Variante</th><th>p50 (ms)</th><th>p95 (ms)</th><th>Filas leídas</th><th>Bytes leídos</th></tr></thead>
                <tbody>{benchmark.metrics.map(entry => <tr key={entry.query + entry.variant}>
                  <th scope="row">{entry.query}</th><td>{entry.variant}</td><td>{fmt(entry.p50_ms)}</td><td>{fmt(entry.p95_ms)}</td>
                  <td>{fmt(entry.read_rows)}</td><td>{fmt(entry.read_bytes)}</td>
                </tr>)}</tbody>
              </table></div>
            </div>}
          </section>
        </>}
      </div>
    </main>
    <footer><div className="shell">Pulso Chicago · Explorador OLAP de movilidad urbana</div></footer>
  </>;
}

createRoot(document.getElementById('root')!).render(<App />);
