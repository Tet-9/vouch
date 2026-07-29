import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'

vi.mock('../lib/rpc', async () => {
  const actual = await vi.importActual<typeof import('../lib/rpc')>('../lib/rpc')
  return { ...actual, rpc: vi.fn(), fetchHealth: vi.fn(), fetchCapabilities: vi.fn() }
})
import { fetchCapabilities, fetchHealth, rpc, VouchRpcError } from '../lib/rpc'
import { makeProject, renderWithProviders, seedConnection } from '../test/utils'
import { ArtifactDrawer } from './ArtifactDrawer'

const CAPS = {
  name: 'vouch',
  level: 3,
  methods: ['kb.read_claim', 'kb.cite', 'kb.why', 'kb.read_page'],
  review_gated: true,
}

const CLAIM = {
  id: 'the-vouch-http-server-binds-127-0-0-1-8731-by-default',
  text: 'The vouch HTTP server binds 127.0.0.1:8731 by default',
  type: 'observation',
  status: 'working',
  confidence: 0.7,
  created_at: '2026-07-04T02:17:50+00:00',
}

const WHY = {
  root: CLAIM.id,
  node_kind: 'claim',
  depth: 3,
  provenance: [
    { kind: 'approvedBy', target: '03f7', target_kind: 'event', event_ts: null, session_id: null, cycle: false, children: [] },
    { kind: 'cites', target: 'ea1cc580', target_kind: 'source', event_ts: null, session_id: null, cycle: false, children: [] },
  ],
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(fetchHealth).mockResolvedValue(true)
  vi.mocked(fetchCapabilities).mockResolvedValue(CAPS)
  seedConnection()
})

test('renders nothing for a null target', () => {
  const { container } = renderWithProviders(<ArtifactDrawer target={null} project={makeProject(CAPS)} onClose={() => {}} />)
  expect(container.querySelector('[data-testid="drawer"]')).toBeNull()
})

test('shows a Delete button when kb.propose_delete is advertised', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return WHY
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: [...CAPS.methods, 'kb.propose_delete'] }
  renderWithProviders(
    <ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(caps)} onClose={() => {}} />,
  )
  expect(await screen.findByRole('button', { name: /delete/i })).toBeInTheDocument()
})

test('shows Archive and Supersede for a claim when advertised', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return WHY
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: [...CAPS.methods, 'kb.archive', 'kb.supersede'] }
  renderWithProviders(
    <ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(caps)} onClose={() => {}} />,
  )
  expect(await screen.findByRole('button', { name: /archive/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /supersede/i })).toBeInTheDocument()
})

test('loads and renders a claim with citations and provenance', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return [{ id: 'ea1cc580', title: 'note.txt' }]
    if (method === 'kb.why') return WHY
    throw new Error(`unexpected ${method}`)
  })
  renderWithProviders(<ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(CAPS)} onClose={() => {}} />)
  expect(await screen.findByText(CLAIM.text)).toBeInTheDocument()
  expect(screen.getByText(/observation/)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/approvedBy/)).toBeInTheDocument())
  expect(screen.getByText(/cites/)).toBeInTheDocument()
})

test('close button fires onClose', async () => {
  // Per-method mock: a blanket mockResolvedValue(CLAIM) would make kb.why
  // return a Claim and crash the provenance render on `.provenance.length`.
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return { root: CLAIM.id, node_kind: 'claim', depth: 3, provenance: [] }
    throw new Error(`unexpected ${method}`)
  })
  const onClose = vi.fn()
  renderWithProviders(<ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(CAPS)} onClose={onClose} />)
  await userEvent.click(await screen.findByRole('button', { name: /close/i }))
  expect(onClose).toHaveBeenCalled()
})

test('clicking an event provenance target expands the audit event', async () => {
  const EVENT_ID = 'a033fff962f74b6c859b765475a718fe'
  const why = {
    ...WHY,
    provenance: [
      { kind: 'approvedBy', target: EVENT_ID, target_kind: 'event', event_ts: null, session_id: null, cycle: false, children: [] },
    ],
  }
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return why
    if (method === 'kb.audit')
      return {
        events: [
          {
            id: EVENT_ID,
            event: 'proposal.claim.approve',
            actor: 'a',
            created_at: '2026-07-28T06:31:52.095084Z',
            object_ids: [CLAIM.id],
            data: { reason: 'bulk-approve backlog' },
          },
        ],
      }
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: [...CAPS.methods, 'kb.audit'] }
  renderWithProviders(
    <ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(caps)} onClose={() => {}} />,
  )
  await userEvent.click(await screen.findByRole('button', { name: EVENT_ID.slice(0, 24) }))
  const detail = await screen.findByTestId('event-detail')
  expect(detail).toHaveTextContent('proposal.claim.approve')
  expect(detail).toHaveTextContent('bulk-approve backlog')
  // toggle closed again
  await userEvent.click(screen.getByRole('button', { name: EVENT_ID.slice(0, 24) }))
  expect(screen.queryByTestId('event-detail')).toBeNull()
})

test('event target stays plain text when kb.audit is not advertised', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return WHY
    throw new Error(`unexpected ${method}`)
  })
  renderWithProviders(
    <ArtifactDrawer target={{ kind: 'claim', id: CLAIM.id }} project={makeProject(CAPS)} onClose={() => {}} />,
  )
  await waitFor(() => expect(screen.getByText('03f7')).toBeInTheDocument())
  expect(screen.queryByRole('button', { name: '03f7' })).toBeNull()
})

test('clicking a claim provenance target fires onOpen', async () => {
  const why = {
    ...WHY,
    provenance: [
      { kind: 'supersedes', target: 'older-claim-id', target_kind: 'claim', event_ts: null, session_id: null, cycle: false, children: [] },
    ],
  }
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return []
    if (method === 'kb.why') return why
    throw new Error(`unexpected ${method}`)
  })
  const onOpen = vi.fn()
  renderWithProviders(
    <ArtifactDrawer
      target={{ kind: 'claim', id: CLAIM.id }}
      project={makeProject(CAPS)}
      onClose={() => {}}
      onOpen={onOpen}
    />,
  )
  await userEvent.click(await screen.findByRole('button', { name: 'older-claim-id' }))
  expect(onOpen).toHaveBeenCalledWith('claim', 'older-claim-id')
})

test('renders an evidence artifact and links its source', async () => {
  const SRC = 'a'.repeat(64)
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_evidence')
      return {
        id: 'ev-runbook',
        source_id: SRC,
        locator: 'L10-L12',
        quote: 'the retry limit is 3',
        byte_start: 120,
        byte_end: 140,
        created_at: '2026-07-28T06:00:00+00:00',
      }
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: ['kb.read_evidence', 'kb.read_source'] }
  const onOpen = vi.fn()
  renderWithProviders(
    <ArtifactDrawer
      target={{ kind: 'evidence', id: 'ev-runbook' }}
      project={makeProject(caps)}
      onClose={() => {}}
      onOpen={onOpen}
    />,
  )
  expect(await screen.findByText('the retry limit is 3')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: SRC }))
  expect(onOpen).toHaveBeenCalledWith('source', SRC)
})

test('citation rows open the cited evidence', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method) => {
    if (method === 'kb.read_claim') return CLAIM
    if (method === 'kb.cite') return [{ id: 'ev-runbook-retry', locator: 'L1', quote: 'q' }]
    if (method === 'kb.why') return { ...WHY, provenance: [] }
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: [...CAPS.methods, 'kb.read_evidence'] }
  const onOpen = vi.fn()
  renderWithProviders(
    <ArtifactDrawer
      target={{ kind: 'claim', id: CLAIM.id }}
      project={makeProject(caps)}
      onClose={() => {}}
      onOpen={onOpen}
    />,
  )
  await userEvent.click(await screen.findByRole('button', { name: /ev-runbook-retry/ }))
  expect(onOpen).toHaveBeenCalledWith('evidence', 'ev-runbook-retry')
})

test('relation endpoints resolve their kind and open', async () => {
  vi.mocked(rpc).mockImplementation(async (_c, method, params) => {
    if (method === 'kb.read_relation')
      return { id: 'rel-1', source: 'ent-a', relation: 'relates_to', target: 'ent-b', confidence: 0.7 }
    if (method === 'kb.read_claim') throw new VouchRpcError('not_found', 'no such claim')
    if (method === 'kb.read_entity' && (params as { entity_id: string }).entity_id === 'ent-a')
      return { id: 'ent-a', name: 'A', type: 'concept' }
    throw new Error(`unexpected ${method}`)
  })
  const caps = { ...CAPS, methods: [...CAPS.methods, 'kb.read_relation', 'kb.read_entity'] }
  const onOpen = vi.fn()
  renderWithProviders(
    <ArtifactDrawer
      target={{ kind: 'relation', id: 'rel-1' }}
      project={makeProject(caps)}
      onClose={() => {}}
      onOpen={onOpen}
    />,
  )
  await userEvent.click(await screen.findByRole('button', { name: 'ent-a' }))
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith('entity', 'ent-a'))
})

test('shows an ErrorCard when the artifact cannot be read', async () => {
  vi.mocked(rpc).mockRejectedValue(new VouchRpcError('not_found', 'claim missing-id not found'))
  renderWithProviders(<ArtifactDrawer target={{ kind: 'claim', id: 'missing-id' }} project={makeProject(CAPS)} onClose={() => {}} />)
  expect(await screen.findByText(/claim missing-id not found/)).toBeInTheDocument()
})
