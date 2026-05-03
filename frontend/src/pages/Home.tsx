import { useCallback, useEffect, useState } from 'react'

interface HealthResult {
  ok?: boolean
  service?: string
  service_version?: string
  python_version?: string
  nautilus_trader_version?: string | null
  techie_cortex_version?: string | null
  httpx_version?: string | null
}

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
  // Cortex wraps action results — accept either the raw return or { result: ... }.
  return (body?.result ?? body) as T
}

export function HomePage() {
  const [health, setHealth] = useState<HealthResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const h = await callAction<HealthResult>('health')
      setHealth(h)
    } catch (e) {
      setErr(String(e))
      setHealth(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const nautilusOk = !!health?.nautilus_trader_version

  return (
    <div className="max-w-[700px] mx-auto p-5">
      <div className="flex items-baseline justify-between mb-5">
        <h1 className="text-amber-300 text-lg font-semibold m-0">
          Backtester{' '}
          <small className="text-neutral-500 text-[11px] font-normal ml-2">
            local · NautilusTrader engine
          </small>
        </h1>
        <button
          onClick={() => void refresh()}
          disabled={loading}
          className="bg-neutral-800 border border-neutral-700 rounded px-2.5 py-1 text-xs text-neutral-200 hover:bg-neutral-700 cursor-pointer disabled:opacity-50"
        >
          {loading ? 'Checking…' : 'Refresh'}
        </button>
      </div>

      {err && (
        <div className="mb-4 p-3 rounded border border-red-900 bg-red-900/20 text-red-300 text-[12px]">
          <div className="font-medium mb-1">Health check failed</div>
          <div className="font-mono text-[11px] break-all">{err}</div>
          <div className="mt-2 text-neutral-400 text-[11px]">
            Is the backend running?{' '}
            <span className="font-mono">poetry install</span> +{' '}
            <span className="font-mono">start.bat</span>
          </div>
        </div>
      )}

      {health && (
        <div className="bg-neutral-900 border border-neutral-800 rounded p-4">
          <div className="flex items-center gap-2 mb-3">
            <span
              className={
                'inline-block w-2 h-2 rounded-full ' +
                (nautilusOk ? 'bg-teal-400' : 'bg-red-400')
              }
            />
            <span className="text-[13px] text-neutral-200">
              {nautilusOk
                ? 'Engine ready'
                : 'NautilusTrader is NOT importable — the engine cannot run'}
            </span>
          </div>
          <dl className="grid grid-cols-[180px_1fr] gap-y-1.5 gap-x-3 text-[12px]">
            <dt className="text-neutral-500">Service</dt>
            <dd className="text-neutral-200 font-mono">
              {health.service} v{health.service_version}
            </dd>
            <dt className="text-neutral-500">Python</dt>
            <dd className="text-neutral-200 font-mono">
              {health.python_version}
            </dd>
            <dt className="text-neutral-500">nautilus_trader</dt>
            <dd
              className={
                'font-mono ' +
                (nautilusOk ? 'text-teal-300' : 'text-red-300')
              }
            >
              {health.nautilus_trader_version ?? '(not installed)'}
            </dd>
            <dt className="text-neutral-500">techie-cortex</dt>
            <dd className="text-neutral-200 font-mono">
              {health.techie_cortex_version ?? '—'}
            </dd>
            <dt className="text-neutral-500">httpx</dt>
            <dd className="text-neutral-200 font-mono">
              {health.httpx_version ?? '—'}
            </dd>
          </dl>
        </div>
      )}

      <div className="mt-5 text-[11px] text-neutral-600">
        Inc 1 = health probe only. Inc 2 wires up techie-historical-data.
        Inc 3 runs the first end-to-end backtest. See the build plan in{' '}
        <span className="font-mono">techie-trader/doc/dev/backtester/</span>.
      </div>
    </div>
  )
}
