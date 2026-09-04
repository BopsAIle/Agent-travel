import { useEffect, useMemo, useState } from 'react';
import { FaClock, FaCoins, FaBolt, FaExclamationTriangle } from 'react-icons/fa';
import { API_BASE, readError } from '../api';
import { useAuth } from '../context/AuthContext';
import './AgentMonitor.css';

function formatDuration(ms) {
  const value = Number(ms) || 0;
  if (value < 1000) return `${Math.round(value)} ms`;
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.round((value % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function formatCost(usd) {
  const value = Number(usd) || 0;
  if (value === 0) return '$0.00';
  if (value < 0.0001) return `$${value.toExponential(2)}`;
  if (value < 0.01) return `$${value.toFixed(6)}`;
  return `$${value.toFixed(4)}`;
}

function formatTokens(count) {
  const value = Number(count) || 0;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function formatTime(timestamp) {
  if (!timestamp) return '';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function kindLabel(kind) {
  if (kind === 'llm') return 'LLM';
  if (kind === 'http') return 'HTTP';
  if (kind === 'embed') return 'Embed';
  return 'Agent';
}

function AgentMonitor() {
  const { logout, authHeaders } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [selectedRunId, setSelectedRunId] = useState('');
  const [detail, setDetail] = useState(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadOverview = async () => {
    try {
      const response = await fetch(`${API_BASE}/metrics/agents`, { headers: authHeaders() });
      if (response.status === 401 || response.status === 403) {
        logout();
        return;
      }
      if (!response.ok) {
        setError(await readError(response));
        return;
      }
      const payload = await response.json();
      setData(payload);
      setError('');
    } catch {
      setError('Could not load agent metrics.');
    }
  };

  useEffect(() => {
    loadOverview();
    const timer = setInterval(loadOverview, 10000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    const loadDetail = async () => {
      setLoadingDetail(true);
      try {
        const response = await fetch(`${API_BASE}/metrics/runs/${selectedRunId}`, {
          headers: authHeaders(),
        });
        if (response.status === 401 || response.status === 403) {
          logout();
          return;
        }
        if (!response.ok) {
          setError(await readError(response));
          return;
        }
        const payload = await response.json();
        if (!cancelled) setDetail(payload);
      } catch {
        if (!cancelled) setError('Could not load that run.');
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    };
    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  const agents = data?.agents || [];
  const maxDuration = Math.max(1, ...agents.map((item) => item.duration_ms || 0));
  const maxCost = Math.max(0.0000001, ...agents.map((item) => item.cost_usd || 0));
  const summary = data?.summary;
  const spans = detail?.spans || [];
  const spanMax = Math.max(1, ...spans.map((item) => item.duration_ms || 0));

  const activeAgents = useMemo(
    () => agents.filter((item) => item.calls || item.llm_calls || item.http_calls || item.embed_calls),
    [agents]
  );

  return (
    <div className="agent-monitor">
      {error && <div className="error-message">{error}</div>}

      <section className="monitor-kpis">
        <article className="monitor-kpi">
          <span className="monitor-kpi-icon"><FaBolt /></span>
          <div>
            <p className="monitor-kpi-label">Runs</p>
            <p className="monitor-kpi-value">{summary?.runs || 0}</p>
          </div>
        </article>
        <article className="monitor-kpi">
          <span className="monitor-kpi-icon"><FaClock /></span>
          <div>
            <p className="monitor-kpi-label">Wall time</p>
            <p className="monitor-kpi-value">{formatDuration(summary?.duration_ms)}</p>
          </div>
        </article>
        <article className="monitor-kpi">
          <span className="monitor-kpi-icon"><FaCoins /></span>
          <div>
            <p className="monitor-kpi-label">Est. API cost</p>
            <p className="monitor-kpi-value">{formatCost(summary?.cost_usd)}</p>
          </div>
        </article>
        <article className="monitor-kpi">
          <span className="monitor-kpi-icon"><FaExclamationTriangle /></span>
          <div>
            <p className="monitor-kpi-label">Tokens in / out</p>
            <p className="monitor-kpi-value">
              {formatTokens(summary?.input_tokens)} / {formatTokens(summary?.output_tokens)}
            </p>
          </div>
        </article>
      </section>

      <p className="monitor-note">
        Cost is estimated from provider list prices (OpenAI gpt-5.6-luna, Gemini 2.5 Flash, embedding-004).
        Flight, hotel, and event wall times can overlap because those agents run in parallel.
      </p>

      {!summary?.runs && (
        <div className="monitor-empty">
          No agent runs yet. Send a chat message or generate a trip, then this page will fill in.
        </div>
      )}

      <section className="monitor-panel">
        <div className="monitor-panel-head">
          <h2>Per agent</h2>
          <span>{activeAgents.length} with activity</span>
        </div>
        <div className="monitor-table-wrap">
          <table className="monitor-table">
            <thead>
              <tr>
                <th>Agent</th>
                <th>Calls</th>
                <th>Time</th>
                <th>Avg</th>
                <th>LLM</th>
                <th>HTTP</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <tr key={agent.agent} className={agent.calls || agent.llm_calls ? '' : 'is-idle'}>
                  <td>
                    <strong>{agent.label}</strong>
                    <span className="monitor-role">{agent.role}</span>
                    <div className="monitor-bars">
                      <span
                        className="monitor-bar time"
                        style={{ width: `${Math.max(4, (agent.duration_ms / maxDuration) * 100)}%` }}
                      />
                      <span
                        className="monitor-bar cost"
                        style={{ width: `${Math.max(4, (agent.cost_usd / maxCost) * 100)}%` }}
                      />
                    </div>
                  </td>
                  <td>{agent.calls}</td>
                  <td>{formatDuration(agent.duration_ms)}</td>
                  <td>{formatDuration(agent.avg_ms)}</td>
                  <td>{agent.llm_calls}</td>
                  <td>{agent.http_calls}</td>
                  <td>
                    {formatTokens(agent.input_tokens)} / {formatTokens(agent.output_tokens)}
                  </td>
                  <td>{formatCost(agent.cost_usd)}</td>
                  <td className={agent.errors ? 'is-error' : ''}>{agent.errors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <div className="monitor-split">
        <section className="monitor-panel">
          <div className="monitor-panel-head">
            <h2>Recent runs</h2>
            <button type="button" className="monitor-refresh" onClick={loadOverview}>
              Refresh
            </button>
          </div>
          <div className="monitor-run-list">
            {(data?.runs || []).length === 0 && <p className="monitor-muted">No runs stored yet.</p>}
            {(data?.runs || []).map((run) => (
              <button
                type="button"
                key={run.id}
                className={`monitor-run${run.id === selectedRunId ? ' active' : ''}`}
                onClick={() => setSelectedRunId(run.id)}
              >
                <div className="monitor-run-top">
                  <strong>{run.route || run.kind}</strong>
                  <span className={`monitor-status ${run.status}`}>{run.status}</span>
                </div>
                <div className="monitor-run-meta">
                  <span>{formatTime(run.started_at)}</span>
                  <span>{formatDuration(run.duration_ms)}</span>
                  <span>{formatCost(run.cost_usd)}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        <section className="monitor-panel">
          <div className="monitor-panel-head">
            <h2>Run timeline</h2>
            {detail?.run && <span>{formatDuration(detail.run.duration_ms)}</span>}
          </div>
          {!selectedRunId && <p className="monitor-muted">Select a run to see each agent span.</p>}
          {loadingDetail && <p className="monitor-muted">Loading spans…</p>}
          {detail?.run && (
            <div className="monitor-run-summary">
              <span>{detail.run.kind} · {detail.run.route || 'n/a'}</span>
              <span>{formatTokens(detail.run.input_tokens)} in / {formatTokens(detail.run.output_tokens)} out</span>
              <span>{formatCost(detail.run.cost_usd)}</span>
            </div>
          )}
          <div className="monitor-spans">
            {spans.map((span) => (
              <div key={span.id} className={`monitor-span kind-${span.kind}`}>
                <div className="monitor-span-head">
                  <strong>{span.label}</strong>
                  <span className="monitor-kind">{kindLabel(span.kind)}</span>
                  <span>{formatDuration(span.duration_ms)}</span>
                  {span.cost_usd > 0 && <span>{formatCost(span.cost_usd)}</span>}
                </div>
                <div className="monitor-span-track">
                  <span style={{ width: `${Math.max(6, (span.duration_ms / spanMax) * 100)}%` }} />
                </div>
                <div className="monitor-span-meta">
                  {span.model && <span>{span.model}</span>}
                  {(span.input_tokens + span.output_tokens) > 0 && (
                    <span>
                      {span.input_tokens} / {span.output_tokens} tok
                    </span>
                  )}
                  {span.extra?.url && <span className="monitor-url">{span.extra.url}</span>}
                  {span.status !== 'ok' && <span className="is-error">{span.error || span.status}</span>}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="monitor-panel">
        <div className="monitor-panel-head">
          <h2>Price table used for estimates</h2>
        </div>
        <div className="monitor-pricing">
          {(data?.pricing || []).map((item) => (
            <article key={item.model}>
              <strong>{item.model}</strong>
              <span>{item.provider}</span>
              <p>
                ${item.input_per_million.toFixed(3)} / 1M in
                {item.output_per_million
                  ? ` · $${item.output_per_million.toFixed(2)} / 1M out`
                  : ' · embeddings billed on input only'}
              </p>
              <small>{item.note}</small>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

export default AgentMonitor;