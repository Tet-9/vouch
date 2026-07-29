import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { EmptyState } from '../components/EmptyState'
import { ErrorCard } from '../components/ErrorCard'
import { useErrorToast } from '../components/Toast'
import { useConnection } from '../connection/ConnectionContext'
import type { ProjectState } from '../connection/ConnectionContext'
import { useFanout } from '../lib/fanout'
import type { Page } from '../lib/types'

/** Shape of the enrich pipeline's metadata on a type=session page. */
interface SessionSubject {
  name: string
  type?: string
  description?: string
}
interface SessionMeta {
  session_id?: string
  enrich_summary?: string
  subjects?: SessionSubject[]
}

function meta(page: Page): SessionMeta {
  const m = page.metadata
  return m && typeof m === 'object' ? (m as SessionMeta) : {}
}

interface Row {
  project: ProjectState
  page: Page
}

export function SessionsView() {
  const { aggregated } = useConnection()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('')

  const result = useFanout<Page[]>(['list', 'session-page'], 'kb.list_pages', { type: 'session' })
  useErrorToast(result.errors.length > 0, result.errors[0]?.error)

  const needle = filter.trim().toLowerCase()
  const rows: Row[] = result.rows
    .flatMap((r) => r.data.map((page) => ({ project: r.project, page })))
    .filter(({ page }) => {
      if (needle === '') return true
      const m = meta(page)
      return [page.title, page.id, m.enrich_summary ?? '', ...(m.subjects ?? []).map((s) => s.name)]
        .some((text) => text.toLowerCase().includes(needle))
    })
    .sort((a, b) => (b.page.created_at ?? '').localeCompare(a.page.created_at ?? ''))

  const openPage = ({ page, project }: Row) => {
    const p = aggregated ? `?p=${encodeURIComponent(project.conn.endpoint)}` : ''
    navigate(`/browse/page/${encodeURIComponent(page.id)}${p}`)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-4 border-b border-rule px-6 py-3">
        <p className="text-sm text-ink-2">
          {rows.length} compiled session{rows.length === 1 ? '' : 's'}
        </p>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter…"
          className="ml-auto w-56 rounded-lg border border-rule bg-paper-2 px-3 py-1.5 text-sm text-ink outline-none placeholder:text-sepia focus:border-accent"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {result.unavailable && (
          <EmptyState
            title="Sessions are not available on this endpoint"
            hint="kb.list_pages is not advertised in /capabilities."
          />
        )}
        {!result.unavailable && result.isPending && <p className="text-sm text-sepia">loading…</p>}
        {result.isError && (
          <ErrorCard
            code={(result.errors[0]?.error as { code?: string })?.code}
            message={
              result.errors[0]?.error instanceof Error
                ? result.errors[0].error.message
                : 'failed to load'
            }
          />
        )}
        {!result.unavailable && !result.isPending && !result.isError && rows.length === 0 && (
          <EmptyState
            title={needle ? 'No matches' : 'No compiled sessions yet'}
            hint={
              needle
                ? 'Try a different filter.'
                : 'Captured conversations appear here once the enrich pipeline compiles them into session pages.'
            }
          />
        )}

        <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
          {rows.map((row) => {
            const { project, page } = row
            const m = meta(page)
            return (
              <li key={`${project.conn.endpoint} ${page.id}`}>
                <button
                  data-testid="session-card"
                  onClick={() => openPage(row)}
                  className="flex h-full w-full flex-col gap-2 rounded-xl border border-rule bg-paper-2 p-4 text-left transition hover:border-accent/50 hover:bg-paper-3"
                >
                  <div className="flex items-baseline gap-2">
                    <p className="min-w-0 flex-1 truncate text-sm font-semibold text-ink">
                      {page.title}
                    </p>
                    <span className="shrink-0 font-mono text-[11px] text-sepia">
                      {(page.created_at ?? '').slice(0, 10)}
                    </span>
                  </div>
                  {m.enrich_summary && (
                    <p className="line-clamp-2 text-sm text-ink-2">{m.enrich_summary}</p>
                  )}
                  {(m.subjects?.length ?? 0) > 0 && (
                    <div className="mt-auto flex flex-wrap gap-1.5 pt-1">
                      {m.subjects!.map((s) => (
                        <span
                          key={s.name}
                          title={s.description}
                          className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent-2"
                        >
                          {s.name}
                        </span>
                      ))}
                    </div>
                  )}
                  <p className="flex items-center gap-2 truncate font-mono text-[11px] text-sepia">
                    {aggregated && (
                      <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[10px] text-accent-2">
                        {project.label}
                      </span>
                    )}
                    {page.id}
                  </p>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
