import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Cytoscape from 'cytoscape';
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  CircleHelp,
  Crosshair,
  Network,
  RotateCcw,
  Upload,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';

const CATEGORY_COLORS = {
  Equities: '#198b78',
  Commodities: '#cb8a2e',
  Currencies: '#597f9a',
  Cryptocurrency: '#9368a7',
  Other: '#89948e',
};

const CATEGORIES = Object.keys(CATEGORY_COLORS);
const HOSTED = !['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);
const MAX_CSV_BYTES = HOSTED ? 3_500_000 : 50 * 1024 * 1024;
const MAX_CSV_LABEL = HOSTED ? '3.5 MB' : '50 MB';

function formatCorrelation(value) {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}`;
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function correlationColor(value) {
  if (value == null || !Number.isFinite(value)) return '#eef1ef';
  const strength = Math.min(0.86, Math.abs(value) * 0.82);
  return value >= 0
    ? `rgba(25, 139, 120, ${strength})`
    : `rgba(209, 93, 93, ${strength})`;
}

function useNetworkData({ threshold, start, end, categories, sampleMode, csvText }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const requestId = useRef(0);

  const refresh = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError('');
    const params = new URLSearchParams({ threshold: String(threshold) });
    if (start) params.set('start', start);
    if (end) params.set('end', end);
    categories.forEach((category) => params.append('categories', category));

    try {
      const response = sampleMode
        ? await fetch(`/api/sample?${params}`)
        : await fetch(`/api/analyze?${params}`, {
          method: 'POST',
          headers: { 'Content-Type': 'text/csv' },
          body: csvText,
        });
      const payload = await response.json();
      if (currentRequest !== requestId.current) return;
      if (!response.ok) {
        throw new Error(payload?.detail?.message || 'Analysis could not be completed.');
      }
      setResult(payload);
    } catch (requestError) {
      if (currentRequest === requestId.current) {
        setError(requestError.message || 'Analysis could not be completed.');
      }
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, [threshold, start, end, categories, sampleMode, csvText]);

  useEffect(() => {
    const timer = window.setTimeout(refresh, 220);
    return () => window.clearTimeout(timer);
  }, [refresh]);

  return { result, loading, error };
}

function RelationshipGraph({ data, selectedId, onSelect, cyRef }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !data) return undefined;

    const nodes = data.assets.map((asset) => ({
      data: {
        id: asset.id,
        label: asset.name,
        category: asset.category,
        color: CATEGORY_COLORS[asset.category] || CATEGORY_COLORS.Other,
        degree: asset.degree,
      },
    }));
    const edges = data.edges.map((edge) => ({
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        correlation: edge.correlation,
        strength: Math.abs(edge.correlation),
        label: formatCorrelation(edge.correlation),
      },
      classes: edge.correlation >= 0 ? 'positive' : 'negative',
    }));

    const cy = Cytoscape({
      container: containerRef.current,
      elements: [...nodes, ...edges],
      minZoom: 0.35,
      maxZoom: 2.5,
      wheelSensitivity: 0.22,
      layout: {
        name: 'cose',
        animate: false,
        fit: true,
        padding: 44,
        nodeRepulsion: 6200,
        idealEdgeLength: 115,
        edgeElasticity: 80,
        gravity: 0.38,
        randomize: true,
      },
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            width: 'mapData(degree, 0, 8, 28, 43)',
            height: 'mapData(degree, 0, 8, 28, 43)',
            color: '#20302a',
            'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif',
            'font-size': 11,
            'font-weight': 600,
            'text-wrap': 'wrap',
            'text-max-width': 100,
            'text-valign': 'bottom',
            'text-margin-y': 8,
            'text-background-color': '#fbfcfb',
            'text-background-opacity': 0.92,
            'text-background-padding': 2,
            'border-width': 2,
            'border-color': '#ffffff',
            'overlay-opacity': 0,
          },
        },
        {
          selector: 'edge',
          style: {
            width: 'mapData(strength, 0, 1, 1.2, 5.4)',
            opacity: 0.58,
            label: 'data(label)',
            color: '#53605a',
            'font-family': 'Inter, ui-sans-serif, system-ui, sans-serif',
            'font-size': 8,
            'text-rotation': 'autorotate',
            'text-background-color': '#ffffff',
            'text-background-opacity': 0.86,
            'text-background-padding': 2,
            'curve-style': 'bezier',
            'overlay-opacity': 0,
          },
        },
        { selector: 'edge.positive', style: { 'line-color': '#198b78', 'line-style': 'solid' } },
        { selector: 'edge.negative', style: { 'line-color': '#d15d5d', 'line-style': 'dashed' } },
        { selector: '.faded', style: { opacity: 0.12 } },
        { selector: 'node:selected', style: { 'border-width': 4, 'border-color': '#17231f' } },
      ],
    });

    cy.on('tap', 'node', (event) => onSelect(event.target.id()));
    cy.on('tap', (event) => {
      if (event.target === cy) onSelect(null);
    });
    let disposed = false;
    const resizeObserver = new ResizeObserver(() => {
      if (disposed) return;
      cy.resize();
      cy.fit(undefined, 38);
    });
    resizeObserver.observe(containerRef.current);
    cyRef.current = cy;
    return () => {
      disposed = true;
      resizeObserver.disconnect();
      cyRef.current = null;
      cy.destroy();
    };
  }, [data, onSelect, cyRef]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.nodes().unselect();
    cy.elements().removeClass('faded');
    if (!selectedId) return;
    const selected = cy.getElementById(selectedId);
    if (!selected.length) return;
    selected.select();
    const neighborhood = selected.closedNeighborhood();
    cy.elements().difference(neighborhood).addClass('faded');
  }, [selectedId, data, cyRef]);

  return <div className="graph-canvas" ref={containerRef} aria-label="Interactive asset relationship graph" />;
}

function Metric({ label, value, hint }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <span className="metric-hint">{hint}</span>
    </div>
  );
}

function RelationshipList({ title, items, positive }) {
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <div className="relationship-list">
      <div className="subhead"><span>{title}</span><Icon size={15} aria-hidden="true" /></div>
      {items.length ? items.map((item) => (
        <div className="relationship-row" key={item.name}>
          <span className="relationship-name">{item.name}</span>
          <span className={positive ? 'corr-value positive-text' : 'corr-value negative-text'}>{formatCorrelation(item.correlation)}</span>
        </div>
      )) : <p className="empty-row">No measurable relationship in this period.</p>}
    </div>
  );
}

function App() {
  const [threshold, setThreshold] = useState(0.4);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [categories, setCategories] = useState([]);
  const [sampleMode, setSampleMode] = useState(true);
  const [csvText, setCsvText] = useState('');
  const [sourceName, setSourceName] = useState('Kaggle public dataset');
  const [selectedId, setSelectedId] = useState(null);
  const [notice, setNotice] = useState('');
  const cyRef = useRef(null);
  const inputRef = useRef(null);
  const { result, loading, error } = useNetworkData({ threshold, start, end, categories, sampleMode, csvText });

  const selectedAsset = useMemo(() => {
    if (!result?.assets?.length) return null;
    return result.assets.find((asset) => asset.id === selectedId) || result.assets[0];
  }, [result, selectedId]);

  const degreeDistribution = result?.stats?.degree_distribution || [];
  const maxDegreeCount = Math.max(1, ...degreeDistribution.map((entry) => entry.assets));
  const availableCategories = result?.category_options || CATEGORIES;

  const toggleCategory = (category) => {
    setCategories((current) => current.includes(category)
      ? current.filter((item) => item !== category)
      : [...current, category]);
    setSelectedId(null);
  };

  const acceptFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setNotice('Choose a .csv file.');
      return;
    }
    if (file.size > MAX_CSV_BYTES) {
      setNotice(`CSV files must be ${MAX_CSV_LABEL} or smaller.`);
      return;
    }
    try {
      const text = await file.text();
      setCsvText(text);
      setSampleMode(false);
      setSourceName(file.name);
      setCategories([]);
      setStart('');
      setEnd('');
      setSelectedId(null);
      setNotice('');
    } catch {
      setNotice('The selected file could not be read.');
    }
  };

  const loadSample = () => {
    setCsvText('');
    setSampleMode(true);
    setSourceName('Kaggle public dataset');
    setCategories([]);
    setStart('');
    setEnd('');
    setSelectedId(null);
    setNotice('');
  };

  const selectAsset = useCallback((id) => setSelectedId(id || null), []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark"><Network size={19} strokeWidth={2.1} /></div>
          <div>
            <div className="brand-name">Market Relationship Atlas</div>
          <div className="brand-subtitle">SIGNED CORRELATION NETWORK // V2.0</div>
          </div>
        </div>
        <div className="topbar-right">
          <span className={`source-badge ${sampleMode ? 'public' : HOSTED ? 'hosted' : 'local'}`}>
            <span className="status-dot" />{sampleMode ? 'Public dataset' : HOSTED ? 'Hosted analysis' : 'Local analysis'}
          </span>
          <button className="icon-button help-button" type="button" title="Analysis notes" aria-label="Analysis notes" onClick={() => setNotice('Edges represent Pearson correlation of simple returns. Correlation is historical association, not causation or a forecast.') }>
            <CircleHelp size={17} />
          </button>
        </div>
      </header>

      <main className="workspace">
        <section className="page-intro">
          <div>
            <div className="eyebrow"><Activity size={13} /> NETWORK ANALYSIS</div>
            <h1>Market relationships</h1>
            <p>Explore how asset returns moved together across a selected historical window.</p>
          </div>
          <div className="intro-actions">
            {sampleMode ? null : <button className="quiet-button" type="button" onClick={loadSample}><RotateCcw size={15} /> Use sample</button>}
            <input ref={inputRef} className="visually-hidden" type="file" accept=".csv,text/csv" onChange={acceptFile} />
            <button className="primary-button" type="button" onClick={() => inputRef.current?.click()}><Upload size={15} /> Import CSV</button>
          </div>
        </section>

        <div className="data-note">
          <span className="note-mark">i</span>
          <span className="note-copy">{sampleMode
            ? result?.dataset
              ? <>
                Built-in source: <strong>{result.dataset.name}</strong> (Kaggle v{result.dataset.version}, CC0) · {result.dataset.raw_rows.toLocaleString()} rows / {result.dataset.raw_assets} assets · snapshot {result.dataset.snapshot_date}; observations through {result.dataset.period.end}. {result.dataset.analyzed_assets} series analyzed; {result.dataset.excluded_assets.join(', ') || 'none'} excluded for non-positive closes. Historical data, not live.{' '}
                <a className="source-link" href={result.dataset.source_url} target="_blank" rel="noreferrer">Source and license</a>
              </>
              : 'Loading the built-in Kaggle public dataset…'
            : HOSTED
              ? 'CSV is sent to Vercel for in-memory analysis (3.5 MB max). This app does not save it; avoid sensitive or confidential data.'
              : 'Local CSV is analyzed in memory. The file is not saved by this application.'}</span>
          {!sampleMode ? <span className="file-name" title={sourceName}>{sourceName}</span> : null}
        </div>
        {notice ? <div className="notice-line" role="status">{notice}</div> : null}
        {error ? <div className="error-line" role="alert">{error}</div> : null}

        <section className="control-strip" aria-label="Analysis filters">
          <div className="control-group threshold-control">
            <div className="control-heading"><label htmlFor="threshold">Minimum |correlation|</label><strong>{threshold.toFixed(2)}</strong></div>
            <input id="threshold" type="range" min="0.1" max="0.9" step="0.01" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} />
            <div className="range-labels"><span>More links</span><span>Stronger links</span></div>
          </div>
          <div className="control-divider" />
          <div className="control-group date-control">
            <label htmlFor="start-date">From</label>
            <input id="start-date" type="date" value={start} onChange={(event) => setStart(event.target.value)} />
          </div>
          <div className="control-group date-control">
            <label htmlFor="end-date">To</label>
            <input id="end-date" type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
          </div>
          <div className="control-spacer" />
          <div className="period-stamp">
            <span>ACTIVE WINDOW</span>
            <strong>{result?.period ? `${result.period.start} - ${result.period.end}` : 'Loading period...'}</strong>
          </div>
        </section>

        <section className="category-strip" aria-label="Asset category filters">
          <span className="filter-label">Asset groups</span>
          <button className={!categories.length ? 'category-chip selected' : 'category-chip'} type="button" onClick={() => { setCategories([]); setSelectedId(null); }}>All</button>
          {availableCategories.map((category) => {
            const active = categories.includes(category);
            return (
              <button key={category} className={`category-chip ${active ? 'selected' : ''}`} type="button" onClick={() => toggleCategory(category)}>
                <span className="category-dot" style={{ backgroundColor: CATEGORY_COLORS[category] }} />{category}
              </button>
            );
          })}
          <span className="filter-summary">{result ? `${result.stats.nodes} assets in view` : ''}</span>
        </section>

        {loading && !result ? <div className="loading-state">Preparing the relationship network...</div> : null}

        {result ? <>
          <section className="metrics-row" aria-label="Network statistics">
            <Metric label="Assets" value={result.stats.nodes} hint={`${result.price_dates.toLocaleString()} price dates`} />
            <Metric label="Relationships" value={result.stats.edges} hint={`${result.stats.positive_edges} positive | ${result.stats.negative_edges} negative`} />
            <Metric label="Network density" value={formatPercent(result.stats.density)} hint="Thresholded graph" />
            <Metric label="Components" value={result.stats.components} hint={`${result.stats.communities.length} detected groups`} />
            <Metric label="Avg. clustering" value={result.stats.average_clustering.toFixed(2)} hint="Absolute edge strength" />
          </section>

          <section className="analysis-layout">
            <div className="graph-panel">
              <div className="panel-heading graph-heading">
                <div>
                  <h2>Relationship network</h2>
                  <p>Node size tracks degree | edge weight tracks correlation strength</p>
                </div>
                <div className="graph-actions" aria-label="Graph controls">
                  <button className="icon-button" type="button" title="Zoom in" aria-label="Zoom in" onClick={() => cyRef.current?.zoom({ level: cyRef.current.zoom() * 1.2, renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } })}><ZoomIn size={16} /></button>
                  <button className="icon-button" type="button" title="Zoom out" aria-label="Zoom out" onClick={() => cyRef.current?.zoom({ level: cyRef.current.zoom() / 1.2, renderedPosition: { x: cyRef.current.width() / 2, y: cyRef.current.height() / 2 } })}><ZoomOut size={16} /></button>
                  <button className="icon-button" type="button" title="Fit graph" aria-label="Fit graph" onClick={() => cyRef.current?.fit(undefined, 36)}><Crosshair size={15} /></button>
                </div>
              </div>
              <div className="graph-stage">
                <RelationshipGraph data={result} selectedId={selectedId} onSelect={selectAsset} cyRef={cyRef} />
                {loading ? <div className="graph-loading">Updating network...</div> : null}
                {!result.edges.length ? <div className="empty-graph">No relationships meet this threshold.</div> : null}
              </div>
              <div className="graph-legend">
                <span><i className="legend-line positive" /> Positive</span>
                <span><i className="legend-line negative" /> Negative</span>
                <span className="legend-hint">Select a node to inspect its neighborhood</span>
              </div>
            </div>

            <aside className="detail-panel" aria-label="Selected asset details">
              <div className="panel-heading detail-heading">
                <div><h2>Asset detail</h2><p>Selected node and its local network</p></div>
              </div>
              {selectedAsset ? <>
                <label className="select-label" htmlFor="asset-picker">ASSET</label>
                <select id="asset-picker" value={selectedAsset.id} onChange={(event) => setSelectedId(event.target.value)}>
                  {result.assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}
                </select>
                <div className="asset-identity">
                  <span className="asset-color" style={{ backgroundColor: CATEGORY_COLORS[selectedAsset.category] || CATEGORY_COLORS.Other }} />
                  <span>{selectedAsset.category}</span>
                  <span className="community-label">Group {selectedAsset.community}</span>
                </div>
                <div className="detail-metrics">
                  <div><span>Degree</span><strong>{selectedAsset.degree}</strong></div>
                  <div><span>Degree centrality</span><strong>{selectedAsset.degree_centrality.toFixed(2)}</strong></div>
                  <div><span>Clustering</span><strong>{selectedAsset.clustering.toFixed(2)}</strong></div>
                  <div><span>Betweenness</span><strong>{selectedAsset.betweenness.toFixed(2)}</strong></div>
                </div>
                <RelationshipList title="Strongest positive" items={selectedAsset.strongest_positive} positive />
                <RelationshipList title="Strongest negative" items={selectedAsset.strongest_negative} positive={false} />
                <div className="degree-block">
                  <div className="subhead"><span>Degree distribution</span><span className="subhead-note">assets by links</span></div>
                  <div className="degree-bars">
                    {degreeDistribution.map((entry) => (
                      <div className="degree-bar-row" key={entry.degree}>
                        <span>{entry.degree}</span>
                        <div className="degree-track"><i style={{ width: `${(entry.assets / maxDegreeCount) * 100}%` }} /></div>
                        <span className="degree-count">{entry.assets}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </> : <div className="empty-detail">Select an asset to see its network metrics.</div>}
            </aside>
          </section>

          <section className="matrix-section">
            <div className="panel-heading matrix-heading">
              <div><h2>Correlation matrix</h2><p>Pearson correlation of simple returns · at least 30 overlapping returns · scroll horizontally to view all assets</p></div>
              <div className="matrix-key"><span className="key-negative">-1</span><i /><span className="key-neutral">0</span><i /><span className="key-positive">+1</span></div>
            </div>
            <div className="matrix-scroll" role="region" aria-label="Correlation matrix table. Scroll horizontally to view all assets." tabIndex="0">
              <table className="matrix-table">
                <caption className="visually-hidden">Pairwise Pearson correlations for {result.assets.length} assets. Select a row or column label to inspect that asset.</caption>
                <colgroup><col className="matrix-label-col" />{result.assets.map((asset) => <col key={asset.id} className="matrix-data-col" />)}</colgroup>
                <thead><tr><th className="matrix-corner" scope="col">ASSET</th>{result.assets.map((asset) => (
                  <th key={asset.id} scope="col" className={selectedAsset?.id === asset.id ? 'active-axis' : ''}>
                    <button type="button" onClick={() => setSelectedId(asset.id)} title={asset.name}>{asset.name}</button>
                  </th>
                ))}</tr></thead>
                <tbody>{result.assets.map((asset, rowIndex) => (
                  <tr key={asset.id} className={selectedAsset?.id === asset.id ? 'active-row' : ''}>
                    <th scope="row"><button type="button" onClick={() => setSelectedId(asset.id)} title={asset.name}>{asset.name}</button></th>
                    {result.matrix[rowIndex].map((value, colIndex) => {
                      const colAsset = result.assets[colIndex];
                      const diagonal = rowIndex === colIndex;
                      return <td key={colAsset.id} className={selectedAsset?.id === colAsset.id ? 'active-axis' : ''}>
                        <button
                          type="button"
                          className={diagonal ? 'matrix-cell diagonal' : 'matrix-cell'}
                          style={{ backgroundColor: correlationColor(value) }}
                          title={`${asset.name} / ${colAsset.name}: ${formatCorrelation(value)}`}
                          onClick={() => setSelectedId(asset.id)}
                          aria-label={`${asset.name} compared with ${colAsset.name}: ${formatCorrelation(value)}`}
                        >{formatCorrelation(value)}</button>
                      </td>;
                    })}
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
          <footer className="page-footer">
            <span>{result.source} | {result.return_observations.toLocaleString()} return dates</span>
            <span>Correlation describes historical association; it does not establish causation.</span>
          </footer>
        </> : null}
      </main>
    </div>
  );
}

export default App;
