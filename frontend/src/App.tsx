import { HomePage } from './pages/Home'

export function App() {
  return (
    <div className="h-screen flex flex-col bg-[#0a0a0a] text-neutral-200">
      <nav className="border-b border-neutral-800 px-5 py-2 flex items-center gap-4 sticky top-0 z-10 bg-[#121212]">
        <span className="text-sm font-semibold text-amber-300 mr-3">
          Techie Backtester
        </span>
        <span className="text-[11px] text-neutral-500">
          Inc 1 — health probe only
        </span>
        <a
          href="/docs"
          target="_blank"
          rel="noopener"
          className="ml-auto text-[11px] text-neutral-500 hover:text-neutral-300"
        >
          /docs
        </a>
      </nav>
      <main className="flex-1 overflow-auto">
        <HomePage />
      </main>
    </div>
  )
}
