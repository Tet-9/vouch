import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, expect, test, vi } from 'vitest'

vi.mock('../lib/rpc', async () => {
  const actual = await vi.importActual<typeof import('../lib/rpc')>('../lib/rpc')
  return { ...actual, rpc: vi.fn(), fetchHealth: vi.fn(), fetchCapabilities: vi.fn() }
})
import { fetchCapabilities, fetchHealth, rpc } from '../lib/rpc'
import { Route, Routes } from 'react-router-dom'
import { renderWithProviders, seedConnection } from '../test/utils'
import { SessionsView } from './SessionsView'

const CAPS = { name: 'vouch', level: 3, methods: ['kb.list_pages'], review_gated: true }

const SESSION_PAGES = [
  {
    id: 'session-fix-the-latin1-locale-crash',
    title: 'session: fix the latin-1 locale crash',
    body: '# session\n…',
    type: 'session',
    status: 'draft',
    created_at: '2026-07-20T09:00:00Z',
    metadata: {
      session_id: 'locale-fix',
      enrich_summary: 'Fixed the stdio crash by reconfiguring utf-8 at cli import.',
      subjects: [{ name: 'locale-crash', type: 'decision', description: 'the crash and its fix' }],
    },
  },
  {
    id: 'session-compare-ditto-with-vouch',
    title: 'session: compare ditto with vouch',
    body: '# session\n…',
    type: 'session',
    status: 'draft',
    created_at: '2026-07-27T07:48:05Z',
    metadata: {
      session_id: 'demo-compare',
      enrich_summary: 'Deep-dived ditto as a competitor and built VouchBench.',
      subjects: [
        { name: 'Ditto', type: 'project', description: 'competitor memory network' },
        { name: 'VouchBench', type: 'project', description: 'benchmark answer' },
      ],
    },
  },
]

function renderSessions() {
  return renderWithProviders(
    <Routes>
      <Route path="/sessions" element={<SessionsView />} />
      <Route path="/browse/:kind?/:id?" element={<p>browse probe</p>} />
    </Routes>,
    { route: '/sessions' },
  )
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  vi.mocked(fetchHealth).mockResolvedValue(true)
  vi.mocked(fetchCapabilities).mockResolvedValue(CAPS)
  vi.mocked(rpc).mockImplementation(async (_c, method, params) => {
    if (method === 'kb.list_pages' && (params as { type?: string })?.type === 'session')
      return SESSION_PAGES
    throw new Error(`unexpected ${method} ${JSON.stringify(params)}`)
  })
  seedConnection()
})

test('lists compiled session cards newest first, with summary and date', async () => {
  renderSessions()
  const cards = await screen.findAllByTestId('session-card')
  expect(cards).toHaveLength(2)
  expect(cards[0]).toHaveTextContent('session: compare ditto with vouch')
  expect(cards[0]).toHaveTextContent('2026-07-27')
  expect(cards[0]).toHaveTextContent(/deep-dived ditto as a competitor/i)
  expect(cards[1]).toHaveTextContent('session: fix the latin-1 locale crash')
})

test('requests only session-type pages from the server', async () => {
  renderSessions()
  await screen.findAllByTestId('session-card')
  expect(rpc).toHaveBeenCalledWith(expect.anything(), 'kb.list_pages', { type: 'session' })
})

test('renders the compiled subjects as chips on each card', async () => {
  renderSessions()
  await screen.findAllByTestId('session-card')
  expect(screen.getByText('Ditto')).toBeInTheDocument()
  expect(screen.getByText('VouchBench')).toBeInTheDocument()
  expect(screen.getByText('locale-crash')).toBeInTheDocument()
})

test('filter narrows cards by title, summary, or subject', async () => {
  renderSessions()
  await screen.findAllByTestId('session-card')
  await userEvent.type(screen.getByPlaceholderText(/filter/i), 'VouchBench')
  expect(screen.getAllByTestId('session-card')).toHaveLength(1)
  expect(screen.queryByText('session: fix the latin-1 locale crash')).not.toBeInTheDocument()
})

test('clicking a card deep-links into the browse page drawer', async () => {
  renderSessions()
  const cards = await screen.findAllByTestId('session-card')
  await userEvent.click(cards[0])
  expect(await screen.findByText('browse probe')).toBeInTheDocument()
})

test('empty result shows an instructive empty state', async () => {
  vi.mocked(rpc).mockResolvedValue([])
  renderSessions()
  expect(await screen.findByText(/no compiled sessions yet/i)).toBeInTheDocument()
})

test('un-advertised kb.list_pages renders an unavailable note, not endless loading', async () => {
  vi.mocked(fetchCapabilities).mockResolvedValue({ ...CAPS, methods: ['kb.list_claims'] })
  renderSessions()
  expect(await screen.findByText(/not available on this endpoint/i)).toBeInTheDocument()
})
