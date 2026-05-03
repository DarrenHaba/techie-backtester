import { useCallback, useEffect, useMemo, useState } from 'react'

// ---------- types ----------

interface HealthResult {
  ok?: boolean
  service?: string
  service_version?: string
  python_version?: string
  nautilus_trader_version?: string | null
  techie_cortex_version?: string | null
  httpx_version?: string | null
}

interface EquityPoint {
  timestamp: string
  equity: number
}

interface Trade {
  position_id?: string
  instrument_id?: string
  entry?: string
  side?: string
  ts_opened?: string
  ts_closed?: string
  avg_px_open?: number
  avg_px_close?: number
  realized_pnl?: string | number
  realized_return?: number
  peak_qty?: string
}

interface BacktestStats {
  starting_equity?: number | null
  ending_equity?: number | null
  total_return_pct?: number | null
  realized_pnl?: number | null
  sharpe_ratio?: number | null
  max_drawdown_pct?: number | null
  trade_count?: number
  bar_count?: number
  bars_dropped_invalid?: number
}

interface BacktestResult {
  ok: boolean
  error?: string
  hint?: string
  symbol?: string
  stats?: BacktestStats
  extra_stats?: Record<string, number>
  equity_curve?: EquityPoint[]
  trades?: Trade[]
  fills?: Array<Record<string, unknown>>
  request?: {
    symbol?: string
    start?: string
    end?: string
    timeframe?: string
    starting_cash?: number
    trade_size?: number
    strategy?: string
  }
}

// ---------- api helper ----------

async function callAction<T>(id: string, args: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`/api/actions/${id}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`action ${id} failed (${res.status}): ${text}`)
  }
  const body = await res.json()
  return (body?.result ?? body) as T
}

// ---------- formatters ----------

function fmtMoney(n: number | null | undefined): string {
  if (n == null) return '—'
  return n.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  })
}

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—'
  return n.toFixed(digits)
}

function fmtDate(s: string | undefined): string {
  if (!s) return '—'
  return s.slice(0, 10)
}

function parseRealizedPnl(v: string | number | undefined): number | null {
  if (v == null) return null
  if (typeof v === 'number') return v
  // Nautilus formats as "6710.00 USD"
  const num = parseFloat(String(v).replace(/[^0-9.\-]/g, ''))
  return isNaN(num) ? null : num
}

// ---------- equity curve mini chart ----------

function EquityCurveSvg({ points }: { points: EquityPoint[] }) {
  // Pure-SVG line chart. No chart library on the dependency list yet.
  const width = 700
  const height = 240
  const padL = 60
  const padR = 14
  const padT = 14
  const padB = 32

  const data = useMemo(() => {
    return points
      .map((p, i) => ({
        i,
        ts: p.timestamp,
        v: typeof p.equity === 'number' ? p.equity : Number(p.equity),
      }))
      .filter((d) => Number.isFinite(d.v))
  }, [points])

  if (data.length < 2) {
    return (
      <div className="text-[12px] text-neutral-500 italic">
        Not enough equity points to chart ({data.length}). Nautilus's
        account_report only emits a row per cash event — for a full
        mark-to-market curve we'd need to compute equity per bar
        ourselves. Coming next.
      </div>
    )
  }

  const minV = Math.min(...data.map((d) => d.v))
  const maxV = Math.max(...data.map((d) => d.v))
  const span = Math.max(1, maxV - minV)
  const innerW = width - padL - padR
  const innerH = height - padT - padB

  const x = (i: number) => padL + (innerW * i) / Math.max(1, data.length - 1)
  const y = (v: number) => padT + innerH - ((v - minV) / span) * innerH

  const path = data.map((d, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(d.v).toFixed(1)}`).join(' ')

  // y-axis ticks
  const ticks = 4
  const tickVals = Array.from({ length: ticks + 1 }, (_, k) => minV + (span * k) / ticks)

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full h-auto"
      role="img"
      aria-label="Equity curve"
    >
      {/* axes */}
      <line x1={padL} y1={padT} x2={padL} y2={padT + innerH} stroke="#444" strokeWidth={1} />
      <line x1={padL} y1={padT + innerH} x2={padL + innerW} y2={padT + innerH} stroke="#444" strokeWidth={1} />
      {/* y ticks */}
      {tickVals.map((v, k) => (
        <g key={k}>
          <line
            x1={padL - 4}
            y1={y(v)}
            x2={padL + innerW}
            y2={y(v)}
            stroke="#222"
            strokeWidth={1}
          />
          <text
            x={padL - 8}
            y={y(v) + 4}
            fontSize={10}
            fill="#888"
            textAnchor="end"
            fontFamily="monospace"
          >
            {fmtMoney(v)}
          </text>
        </g>
      ))}
      {/* x labels (first / last) */}
      <text x={padL} y={height - 10} fontSize={10} fill="#888" fontFamily="monospace">
        {fmtDate(data[0].ts)}
      </text>
      <text
        x={padL + innerW}
        y={height - 10}
        fontSize={10}
        fill="#888"
        fontFamily="monospace"
        textAnchor="end"
      >
        {fmtDate(data[data.length - 1].ts)}
      </text>
      {/* line */}
      <path d={path} stroke="#fbbf24" strokeWidth={1.5} fill="none" />
      {/* points */}
      {data.map((d, i) => (
        <circle key={i} cx={x(i)} cy={y(d.v)} r={2} fill="#fbbf24" />
      ))}
    </svg>
  )
}

// ---------- header (collapsible engine status) ----------

function EngineStatus({ health }: { health: HealthResult | null }) {
  const ok = !!health?.nautilus_trader_version
  return (
    <div className="flex items-center gap-2 text-[11px] text-neutral-500">
      <span
        className={
          'inline-block w-2 h-2 rounded-full ' +
          (ok ? 'bg-teal-400' : 'bg-red-400')
        }
      />
      <span>
        {ok
          ? `engine ready · nautilus ${health?.nautilus_trader_version}`
          : 'engine NOT ready — nautilus_trader missing'}
      </span>
    </div>
  )
}

// ---------- main page ----------

function daysAgoISO(days: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

export function HomePage() {
  const [health, setHealth] = useState<HealthResult | null>(null)
  const [healthErr, setHealthErr] = useState<string | null>(null)

  // Form state
  const [symbol, setSymbol] = useState('AAPL')
  const [start, setStart] = useState(daysAgoISO(365))
  const [end, setEnd] = useState(daysAgoISO(1))
  const [startingCash, setStartingCash] = useState('100000')
  const [tradeSize, setTradeSize] = useState('100')

  // Run state
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [runErr, setRunErr] = useState<string | null>(null)

  const refreshHealth = useCallback(async () => {
    try {
      const h = await callAction<HealthResult>('health')
      setHealth(h)
      setHealthErr(null)
    } catch (e) {
      setHealthErr(String(e))
      setHealth(null)
    }
  }, [])

  useEffect(() => {
    void refreshHealth()
  }, [refreshHealth])

  const run = useCallback(async () => {
    setRunning(true)
    setResult(null)
    setRunErr(null)
    try {
      const r = await callAction<BacktestResult>('run_backtest', {
        symbol: symbol.trim().toUpperCase(),
        start,
        end,
        timeframe: '1d',
        starting_cash: Number(startingCash),
        trade_size: Number(tradeSize),
      })
      setResult(r)
    } catch (e) {
      setRunErr(String(e))
    } finally {
      setRunning(false)
    }
  }, [symbol, start, end, startingCash, tradeSize])

  const stats = result?.stats ?? {}
  const trades = result?.trades ?? []

  return (
    <div className="max-w-[900px] mx-auto p-5">
      <div className="flex items-baseline justify-between mb-1">
        <h1 className="text-amber-300 text-lg font-semibold m-0">
          Backtester{' '}
          <small className="text-neutral-500 text-[11px] font-normal ml-2">
            local · NautilusTrader engine
          </small>
        </h1>
        <button
          onClick={() => void refreshHealth()}
          className="bg-neutral-800 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 hover:bg-neutral-700 cursor-pointer"
        >
          Refresh
        </button>
      </div>
      <div className="mb-5">
        {healthErr ? (
          <div className="text-red-400 text-[11px]">{healthErr}</div>
        ) : (
          <EngineStatus health={health} />
        )}
      </div>

      {/* ---------- form ---------- */}
      <div className="bg-neutral-900 border border-neutral-800 rounded p-4 mb-5">
        <h2 className="m-0 text-neutral-400 text-[11px] uppercase tracking-wider mb-3">
          Run a backtest
        </h2>
        <div className="grid grid-cols-[110px_1fr] gap-y-2 gap-x-3 items-center text-[13px] mb-4">
          <label className="text-neutral-500">Strategy</label>
          <div>
            <span className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-300 font-mono text-xs">
              BuyAndHold
            </span>
            <span className="text-[11px] text-neutral-600 ml-2">
              built-in toy strategy. Real ones land in techie-strategies-private.
            </span>
          </div>
          <label className="text-neutral-500">Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-200 w-[140px] uppercase"
          />
          <label className="text-neutral-500">Timeframe</label>
          <span className="text-neutral-300 font-mono text-xs">1d (daily)</span>
          <label className="text-neutral-500">Start</label>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-200 font-mono text-xs w-[180px]"
          />
          <label className="text-neutral-500">End</label>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-200 font-mono text-xs w-[180px]"
          />
          <label className="text-neutral-500">Starting cash</label>
          <div className="flex items-center gap-2">
            <span className="text-neutral-500">$</span>
            <input
              type="number"
              value={startingCash}
              onChange={(e) => setStartingCash(e.target.value)}
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-200 font-mono text-xs w-[140px]"
            />
          </div>
          <label className="text-neutral-500">Trade size</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={tradeSize}
              onChange={(e) => setTradeSize(e.target.value)}
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-neutral-200 font-mono text-xs w-[140px]"
            />
            <span className="text-[11px] text-neutral-600">shares to buy on first bar</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => void run()}
            disabled={running}
            className="bg-amber-900/40 border border-amber-700 rounded px-4 py-1.5 text-[13px] text-amber-200 hover:bg-amber-900/60 cursor-pointer disabled:opacity-50"
          >
            {running ? 'Running…' : 'Run backtest'}
          </button>
          <span className="text-[11px] text-neutral-600">
            pulls bars from techie-historical-data on :8101 · runs Nautilus engine in a worker thread
          </span>
        </div>
      </div>

      {/* ---------- error ---------- */}
      {runErr && (
        <div className="mb-4 p-3 rounded border border-red-900 bg-red-900/20 text-red-300 text-[12px]">
          <div className="font-medium mb-1">Backtest call failed</div>
          <div className="font-mono text-[11px] break-all">{runErr}</div>
        </div>
      )}

      {result && !result.ok && (
        <div className="mb-4 p-3 rounded border border-red-900 bg-red-900/20 text-red-300 text-[12px]">
          <div className="font-medium mb-1">Backtest returned an error</div>
          <div className="font-mono text-[11px] break-all">{result.error}</div>
          {result.hint && (
            <div className="mt-1 text-neutral-400 text-[11px]">{result.hint}</div>
          )}
        </div>
      )}

      {/* ---------- results ---------- */}
      {result && result.ok && (
        <>
          {/* stat grid */}
          <div className="bg-neutral-900 border border-neutral-800 rounded p-4 mb-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
              <Stat
                label="Total return"
                value={fmtPct(stats.total_return_pct)}
                tone={
                  (stats.total_return_pct ?? 0) >= 0 ? 'pos' : 'neg'
                }
                big
              />
              <Stat
                label="Realized PnL"
                value={fmtMoney(stats.realized_pnl)}
                tone={(stats.realized_pnl ?? 0) >= 0 ? 'pos' : 'neg'}
                big
              />
              <Stat label="Sharpe (252d)" value={fmtNum(stats.sharpe_ratio, 3)} big />
              <Stat
                label="Max drawdown"
                value={
                  stats.max_drawdown_pct == null
                    ? '—'
                    : fmtPct((stats.max_drawdown_pct ?? 0) * 100)
                }
                big
              />
              <Stat label="Starting equity" value={fmtMoney(stats.starting_equity)} />
              <Stat label="Ending equity" value={fmtMoney(stats.ending_equity)} />
              <Stat label="Trade count" value={String(stats.trade_count ?? 0)} />
              <Stat
                label="Bars"
                value={`${stats.bar_count ?? 0}${
                  stats.bars_dropped_invalid
                    ? ` (${stats.bars_dropped_invalid} dropped)`
                    : ''
                }`}
              />
            </div>
          </div>

          {/* equity curve */}
          <div className="bg-neutral-900 border border-neutral-800 rounded p-4 mb-4">
            <h2 className="m-0 text-neutral-400 text-[11px] uppercase tracking-wider mb-2">
              Equity curve
            </h2>
            <EquityCurveSvg points={result.equity_curve ?? []} />
          </div>

          {/* trades */}
          {trades.length > 0 && (
            <div className="bg-neutral-900 border border-neutral-800 rounded p-4 mb-4">
              <h2 className="m-0 text-neutral-400 text-[11px] uppercase tracking-wider mb-2">
                Trades ({trades.length})
              </h2>
              <div className="overflow-auto">
                <table className="w-full text-[12px] border-collapse">
                  <thead>
                    <tr className="text-neutral-500 text-left">
                      <th className="py-1 pr-3 font-normal">Symbol</th>
                      <th className="py-1 pr-3 font-normal">Side</th>
                      <th className="py-1 pr-3 font-normal">Qty</th>
                      <th className="py-1 pr-3 font-normal">Entry</th>
                      <th className="py-1 pr-3 font-normal">Exit</th>
                      <th className="py-1 pr-3 font-normal text-right">Avg open</th>
                      <th className="py-1 pr-3 font-normal text-right">Avg close</th>
                      <th className="py-1 pr-3 font-normal text-right">Realized PnL</th>
                      <th className="py-1 pr-3 font-normal text-right">Return</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => {
                      const pnl = parseRealizedPnl(t.realized_pnl)
                      const ret = t.realized_return == null ? null : t.realized_return * 100
                      return (
                        <tr key={i} className="border-t border-neutral-800 text-neutral-200">
                          <td className="py-1 pr-3 font-mono">{t.instrument_id ?? '—'}</td>
                          <td className="py-1 pr-3 font-mono">{t.entry ?? '—'}</td>
                          <td className="py-1 pr-3 font-mono text-right">{t.peak_qty ?? '—'}</td>
                          <td className="py-1 pr-3 font-mono">{fmtDate(t.ts_opened)}</td>
                          <td className="py-1 pr-3 font-mono">{fmtDate(t.ts_closed)}</td>
                          <td className="py-1 pr-3 font-mono text-right">
                            {fmtNum(t.avg_px_open)}
                          </td>
                          <td className="py-1 pr-3 font-mono text-right">
                            {fmtNum(t.avg_px_close)}
                          </td>
                          <td
                            className={
                              'py-1 pr-3 font-mono text-right ' +
                              ((pnl ?? 0) >= 0 ? 'text-teal-300' : 'text-red-300')
                            }
                          >
                            {fmtMoney(pnl)}
                          </td>
                          <td
                            className={
                              'py-1 pr-3 font-mono text-right ' +
                              ((ret ?? 0) >= 0 ? 'text-teal-300' : 'text-red-300')
                            }
                          >
                            {fmtPct(ret)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* extra stats (full nautilus output) */}
          {result.extra_stats && Object.keys(result.extra_stats).length > 0 && (
            <details className="bg-neutral-900 border border-neutral-800 rounded p-4 mb-4">
              <summary className="cursor-pointer text-neutral-400 text-[11px] uppercase tracking-wider">
                All Nautilus stats ({Object.keys(result.extra_stats).length})
              </summary>
              <dl className="grid grid-cols-[1fr_auto] gap-y-1 gap-x-3 mt-3 text-[12px]">
                {Object.entries(result.extra_stats).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-neutral-500">{k}</dt>
                    <dd className="text-neutral-200 font-mono text-right">
                      {typeof v === 'number' ? v.toFixed(4) : String(v)}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}

          {/* request echo */}
          <div className="text-[11px] text-neutral-600">
            <span className="text-neutral-500">request:</span>{' '}
            <span className="font-mono">
              {result.request?.strategy} · {result.request?.symbol} ·{' '}
              {result.request?.start} → {result.request?.end} · {result.request?.timeframe} ·
              ${result.request?.starting_cash?.toLocaleString()} cash · {result.request?.trade_size} shares
            </span>
          </div>
        </>
      )}

      {!result && !running && !runErr && (
        <div className="text-[12px] text-neutral-500 italic">
          Pick a symbol + window above and hit "Run backtest". Default is
          last year of AAPL daily, $100K cash, buy 100 shares on the first
          bar and hold to the last.
        </div>
      )}
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
  big,
}: {
  label: string
  value: string
  tone?: 'pos' | 'neg'
  big?: boolean
}) {
  const valueClass =
    (big ? 'text-[20px] ' : 'text-[14px] ') +
    'font-mono ' +
    (tone === 'pos'
      ? 'text-teal-300'
      : tone === 'neg'
        ? 'text-red-300'
        : 'text-neutral-200')
  return (
    <div>
      <div className="text-neutral-500 text-[10px] uppercase tracking-wider mb-0.5">
        {label}
      </div>
      <div className={valueClass}>{value}</div>
    </div>
  )
}
