import { useQuery } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useState } from 'react'
import type { ProjectState } from '../connection/ConnectionContext'
import { rpc } from '../lib/rpc'
import type {
  AuditEvent,
  Citation,
  Claim,
  Entity,
  EvidenceRecord,
  Page,
  Relation,
  SourceRecord,
  VouchConnectionInfo,
  WhyEdge,
  WhyResult,
} from '../lib/types'
import { ClaimLifecycleActions } from './ClaimLifecycleActions'
import { DeleteArtifactButton } from './DeleteArtifactButton'
import { ErrorCard } from './ErrorCard'
import { Markdown } from './Markdown'
import { useErrorToast, useToast } from './Toast'

/** Every artifact kind the drawer can display. */
export type OpenKind = 'claim' | 'page' | 'entity' | 'relation' | 'evidence' | 'source'

export type DrawerTarget = { kind: OpenKind; id: string } | null

const READ_METHOD: Record<OpenKind, { method: string; param: string }> = {
  claim: { method: 'kb.read_claim', param: 'claim_id' },
  page: { method: 'kb.read_page', param: 'page_id' },
  entity: { method: 'kb.read_entity', param: 'entity_id' },
  relation: { method: 'kb.read_relation', param: 'relation_id' },
  evidence: { method: 'kb.read_evidence', param: 'evidence_id' },
  source: { method: 'kb.read_source', param: 'source_id' },
}

/** Does the endpoint advertise the read this kind needs? */
function canRead(project: ProjectState, kind: string): kind is OpenKind {
  return (
    kind in READ_METHOD &&
    (project.caps?.methods.includes(READ_METHOD[kind as OpenKind].method) ?? false)
  )
}

// Relation endpoints and audit object_ids arrive without a kind — probe the
// readable kinds in likelihood order and open the first that resolves.
const RESOLVE_ORDER: OpenKind[] = ['claim', 'entity', 'page']

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-rule/60 py-2 text-sm">
      <span className="w-24 shrink-0 text-xs uppercase tracking-wide text-sepia">{label}</span>
      <span className="min-w-0 break-words text-ink-2">{children}</span>
    </div>
  )
}

const ID_LINK_CLASS =
  'break-all text-left font-mono text-xs text-ink-2 underline decoration-rule underline-offset-2 transition hover:text-accent-2'

/** A monospace id — a link when a click handler is given, plain text otherwise. */
function IdRef({ id, shown, onClick }: { id: string; shown?: string; onClick?: () => void }) {
  if (onClick) {
    return (
      <button title={id} onClick={onClick} className={ID_LINK_CLASS}>
        {shown ?? id}
      </button>
    )
  }
  return (
    <span title={id} className="break-all font-mono text-xs text-ink-2">
      {shown ?? id}
    </span>
  )
}

// kb.audit has no by-id read — fetch a deep tail once per endpoint (cached by
// the query client) and pick the event out client-side.
const AUDIT_TAIL = 10_000

/** The audit event behind an approvedBy/decidedBy provenance edge. */
function EventDetail({
  conn,
  id,
  onResolve,
}: {
  conn: VouchConnectionInfo
  id: string
  onResolve?: (id: string) => void
}) {
  const audit = useQuery({
    queryKey: ['audit-tail', conn.endpoint],
    queryFn: () => rpc<{ events: AuditEvent[] }>(conn, 'kb.audit', { tail: AUDIT_TAIL }),
  })
  if (audit.isPending) return <p className="mt-1 text-xs text-sepia">loading event…</p>
  if (audit.isError) {
    return (
      <ErrorCard message={audit.error instanceof Error ? audit.error.message : 'failed to load audit log'} />
    )
  }
  const e = audit.data.events.find((ev) => ev.id === id)
  if (!e) {
    return <p className="mt-1 text-xs text-sepia">event is outside the visible audit window</p>
  }
  const reason = typeof e.data?.reason === 'string' ? e.data.reason : null
  return (
    <div data-testid="event-detail" className="mb-1 mt-1 rounded-lg border border-rule bg-paper px-3 py-1">
      <Row label="event">{e.event}</Row>
      <Row label="actor">{e.actor}</Row>
      <Row label="time">{e.created_at.slice(0, 19).replace('T', ' ')}</Row>
      {reason && <Row label="reason">{reason}</Row>}
      {Array.isArray(e.object_ids) && e.object_ids.length > 0 && (
        <Row label="objects">
          <span className="flex flex-wrap gap-x-2 gap-y-1">
            {e.object_ids.map((oid) => (
              <IdRef key={oid} id={oid} onClick={onResolve ? () => onResolve(oid) : undefined} />
            ))}
          </span>
        </Row>
      )}
    </div>
  )
}

function WhyNode({
  edge,
  depth,
  project,
  onOpen,
  onResolve,
}: {
  edge: WhyEdge
  depth: number
  project: ProjectState
  onOpen?: (kind: OpenKind, id: string) => void
  onResolve?: (id: string) => void
}) {
  const [showEvent, setShowEvent] = useState(false)
  const isEvent = edge.target_kind === 'event' && (project.caps?.methods.includes('kb.audit') ?? false)
  const openable = onOpen !== undefined && canRead(project, edge.target_kind)
  return (
    <li style={{ paddingLeft: depth * 12 }}>
      <span className="font-mono text-xs text-accent-2">{edge.kind}</span>{' '}
      <IdRef
        id={edge.target}
        shown={edge.target.slice(0, 24)}
        onClick={
          isEvent
            ? () => setShowEvent((s) => !s)
            : openable
              ? () => onOpen!(edge.target_kind as OpenKind, edge.target)
              : undefined
        }
      />{' '}
      <span className="text-xs text-sepia">({edge.target_kind})</span>
      {isEvent && showEvent && <EventDetail conn={project.conn} id={edge.target} onResolve={onResolve} />}
      {edge.children.length > 0 && (
        <WhyTree edges={edge.children} depth={depth + 1} project={project} onOpen={onOpen} onResolve={onResolve} />
      )}
    </li>
  )
}

function WhyTree({
  edges,
  depth = 0,
  project,
  onOpen,
  onResolve,
}: {
  edges: WhyEdge[]
  depth?: number
  project: ProjectState
  onOpen?: (kind: OpenKind, id: string) => void
  onResolve?: (id: string) => void
}) {
  return (
    <ul className="space-y-1">
      {edges.map((e, i) => (
        <WhyNode
          key={`${e.kind}-${e.target}-${i}`}
          edge={e}
          depth={depth}
          project={project}
          onOpen={onOpen}
          onResolve={onResolve}
        />
      ))}
    </ul>
  )
}

export function ArtifactDrawer({
  target,
  project,
  onClose,
  onOpen,
}: {
  target: DrawerTarget
  /** The project the artifact lives in — reads route to this endpoint. */
  project: ProjectState | null
  onClose: () => void
  /** When set, ids of readable artifacts render as links that retarget the drawer. */
  onOpen?: (kind: OpenKind, id: string) => void
}) {
  const { toast } = useToast()
  const conn = project?.conn ?? null
  const endpoint = conn?.endpoint
  const has = (m: string) => project?.caps?.methods.includes(m) ?? false

  const read = READ_METHOD[target?.kind ?? 'claim']
  const artifact = useQuery({
    queryKey: ['artifact', endpoint, target?.kind, target?.id],
    queryFn: () => rpc<Record<string, unknown>>(conn!, read.method, { [read.param]: target!.id }),
    enabled: !!conn && !!target,
  })

  const isClaim = target?.kind === 'claim'
  const cite = useQuery({
    queryKey: ['cite', endpoint, target?.id],
    queryFn: () => rpc<Citation[]>(conn!, 'kb.cite', { claim_id: target!.id }),
    enabled: !!conn && isClaim && has('kb.cite'),
  })
  const why = useQuery({
    queryKey: ['why', endpoint, target?.id],
    queryFn: () => rpc<WhyResult>(conn!, 'kb.why', { claim_id: target!.id }),
    enabled: !!conn && isClaim && has('kb.why'),
  })
  useErrorToast(artifact.isError, artifact.error)

  if (!target || !project) return null

  // Kindless ids (relation endpoints, audit object ids): probe the readable
  // kinds and open the first that resolves. Proposal ids resolve to nothing.
  const resolveOpen =
    onOpen &&
    (async (id: string) => {
      for (const kind of RESOLVE_ORDER) {
        if (!canRead(project, kind)) continue
        try {
          await rpc(project.conn, READ_METHOD[kind].method, { [READ_METHOD[kind].param]: id })
          onOpen(kind, id)
          return
        } catch {
          // not this kind — try the next
        }
      }
      toast('error', `${id.slice(0, 24)} is not a readable artifact (a proposal, or deleted)`)
    })
  const resolve = resolveOpen ? (id: string) => void resolveOpen(id) : undefined

  const a = artifact.data

  return (
    <div data-testid="drawer" className="fixed inset-y-0 right-0 z-40 flex w-[28rem] max-w-full flex-col border-l border-rule bg-paper-2 shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-rule px-5 py-4">
        <div className="min-w-0">
          <span className="mr-2 rounded bg-accent/15 px-2 py-0.5 font-mono text-[10px] text-accent-2">
            {project.label}
          </span>
          <span className="rounded bg-paper-3 px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-accent">
            {target.kind}
          </span>
          <p className="mt-1 break-all font-mono text-xs text-sepia">{target.id}</p>
        </div>
        <button aria-label="close" onClick={onClose} className="rounded-lg p-1.5 text-sepia hover:bg-paper-3 hover:text-ink">
          <X size={16} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {artifact.isPending && <p className="text-sm text-sepia">loading…</p>}
        {artifact.isError && (
          <ErrorCard
            code={(artifact.error as { code?: string }).code}
            message={artifact.error instanceof Error ? artifact.error.message : 'failed to load'}
          />
        )}

        {a && target.kind === 'claim' && (
          <>
            <p className="mb-3 text-sm leading-relaxed text-ink">{(a as unknown as Claim).text}</p>
            <Row label="type">{String(a.type)}</Row>
            <Row label="status">{String(a.status)}</Row>
            <Row label="confidence">{Math.round(Number(a.confidence) * 100)}%</Row>
            {typeof a.created_at === 'string' && <Row label="created">{a.created_at.slice(0, 19).replace('T', ' ')}</Row>}
          </>
        )}
        {a && target.kind === 'page' && (
          <>
            <p className="mb-3 text-base font-semibold text-ink">{(a as unknown as Page).title}</p>
            <Row label="type">{String(a.type)}</Row>
            <Row label="status">{String(a.status)}</Row>
            <div className="mt-3">
              <Markdown>{(a as unknown as Page).body}</Markdown>
            </div>
          </>
        )}
        {a && target.kind === 'entity' && (
          <>
            <p className="mb-3 text-base font-semibold text-ink">{(a as unknown as Entity).name}</p>
            <Row label="type">{String(a.type)}</Row>
          </>
        )}
        {a && target.kind === 'relation' && (
          <>
            <Row label="source">
              <IdRef id={(a as unknown as Relation).source} onClick={resolve && (() => resolve((a as unknown as Relation).source))} />
            </Row>
            <Row label="relation">{(a as unknown as Relation).relation}</Row>
            <Row label="target">
              <IdRef id={(a as unknown as Relation).target} onClick={resolve && (() => resolve((a as unknown as Relation).target))} />
            </Row>
            <Row label="confidence">{Math.round(Number(a.confidence) * 100)}%</Row>
          </>
        )}
        {a && target.kind === 'evidence' && (
          <>
            {typeof (a as unknown as EvidenceRecord).quote === 'string' && (
              <blockquote className="mb-3 border-l-2 border-accent/40 pl-3 text-sm italic leading-relaxed text-ink">
                {(a as unknown as EvidenceRecord).quote}
              </blockquote>
            )}
            <Row label="locator">
              <span className="font-mono text-xs">{(a as unknown as EvidenceRecord).locator}</span>
            </Row>
            <Row label="source">
              <IdRef
                id={(a as unknown as EvidenceRecord).source_id}
                onClick={
                  onOpen && canRead(project, 'source')
                    ? () => onOpen('source', (a as unknown as EvidenceRecord).source_id)
                    : undefined
                }
              />
            </Row>
            {(a as unknown as EvidenceRecord).byte_start != null && (a as unknown as EvidenceRecord).byte_end != null && (
              <Row label="receipt">
                <span className="font-mono text-xs">
                  bytes {(a as unknown as EvidenceRecord).byte_start}–{(a as unknown as EvidenceRecord).byte_end}
                </span>
              </Row>
            )}
            {typeof a.created_at === 'string' && <Row label="created">{a.created_at.slice(0, 19).replace('T', ' ')}</Row>}
          </>
        )}
        {a && target.kind === 'source' && (
          <>
            <p className="mb-3 text-base font-semibold text-ink">
              {(a as unknown as SourceRecord).title ?? (a as unknown as SourceRecord).locator}
            </p>
            <Row label="type">{String(a.type)}</Row>
            <Row label="locator">
              <span className="break-all font-mono text-xs">{(a as unknown as SourceRecord).locator}</span>
            </Row>
            <Row label="media">{String(a.media_type)}</Row>
            <Row label="size">{Number(a.byte_size).toLocaleString()} bytes</Row>
            {typeof a.created_at === 'string' && <Row label="created">{a.created_at.slice(0, 19).replace('T', ' ')}</Row>}
          </>
        )}

        {isClaim && cite.data && cite.data.length > 0 && (
          <section className="mt-5">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-sepia">Citations</h3>
            <ul className="space-y-1">
              {cite.data.map((c, i) => {
                // Evidence rows carry an `id`; bare-source rows carry
                // kind:'source' + source_id; missing refs carry neither.
                const evId = c.kind === undefined && typeof c.id === 'string' ? c.id : null
                const srcId = c.kind === 'source' && typeof c.source_id === 'string' ? c.source_id : null
                const open =
                  onOpen && evId && canRead(project, 'evidence')
                    ? () => onOpen('evidence', evId)
                    : onOpen && srcId && canRead(project, 'source')
                      ? () => onOpen('source', srcId)
                      : undefined
                const body = (
                  <>
                    {typeof c.title === 'string' && c.title !== '' ? c.title : null}{' '}
                    <span className="break-all font-mono text-sepia">
                      {typeof c.id === 'string'
                        ? c.id.slice(0, 16)
                        : srcId
                          ? srcId.slice(0, 16)
                          : JSON.stringify(c).slice(0, 60)}
                    </span>
                  </>
                )
                return open ? (
                  <li key={i}>
                    <button
                      onClick={open}
                      className="w-full rounded-lg border border-rule bg-paper px-3 py-2 text-left text-xs text-ink-2 transition hover:border-accent/50"
                    >
                      {body}
                    </button>
                  </li>
                ) : (
                  <li key={i} className="rounded-lg border border-rule bg-paper px-3 py-2 text-xs text-ink-2">
                    {body}
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {isClaim && why.data && why.data.provenance.length > 0 && (
          <section className="mt-5">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-sepia">Why this claim exists</h3>
            <WhyTree edges={why.data.provenance} project={project} onOpen={onOpen} onResolve={resolve} />
          </section>
        )}
      </div>

      {a && (
        <footer className="space-y-3 border-t border-rule px-5 py-4">
          {target.kind === 'claim' && (
            <ClaimLifecycleActions project={project} claimId={target.id} onDone={onClose} />
          )}
          {(target.kind === 'claim' || target.kind === 'page' || target.kind === 'entity' || target.kind === 'relation') && (
            <DeleteArtifactButton project={project} kind={target.kind} id={target.id} onDone={onClose} />
          )}
        </footer>
      )}
    </div>
  )
}
