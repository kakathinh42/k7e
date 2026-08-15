import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import UploadPage from './UploadPage'

vi.mock('../api', () => ({
  uploadDocument: vi.fn(),
  getIngestStatus: vi.fn(),
  listTeams: vi.fn().mockResolvedValue([]),
}))

import { uploadDocument, getIngestStatus } from '../api'

function renderUploadPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <UploadPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const md = (name: string) => new File([`# ${name}`], name, { type: 'text/markdown' })
const fileInput = () => screen.getByLabelText('Choose files') as HTMLInputElement
const dropzone = () => screen.getByRole('button', { name: /drop files here/i })
const uploadBtn = () => screen.getByRole('button', { name: /^Upload/ })

const STORAGE_KEY = 'llmwiki.upload.jobs'

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  vi.mocked(uploadDocument).mockResolvedValue({ raw_document_id: 'r', workflow_id: 'w' })
  vi.mocked(getIngestStatus).mockResolvedValue({
    raw_document_id: 'r', status: 'done', workflow_id: 'w',
  })
})

describe('UploadPage — selection', () => {
  it('adds chosen files to the queue', async () => {
    renderUploadPage()
    fireEvent.change(fileInput(), { target: { files: [md('a.md'), md('b.md')] } })
    expect(await screen.findByText('a.md')).toBeInTheDocument()
    expect(screen.getByText('b.md')).toBeInTheDocument()
    expect(uploadBtn()).toHaveTextContent('Upload 2 files')
  })

  it('adds dropped files to the queue', async () => {
    renderUploadPage()
    fireEvent.drop(dropzone(), { dataTransfer: { files: [md('dropped.md')] } })
    expect(await screen.findByText('dropped.md')).toBeInTheDocument()
  })

  it('caps the queue at 10 files and notifies', async () => {
    renderUploadPage()
    const twelve = Array.from({ length: 12 }, (_, i) => md(`f${i}.md`))
    fireEvent.change(fileInput(), { target: { files: twelve } })
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(10))
    expect(screen.getByText(/Max 10 files/)).toBeInTheDocument()
  })

  it('skips unsupported file types', async () => {
    renderUploadPage()
    const exe = new File(['x'], 'virus.exe', { type: 'application/octet-stream' })
    fireEvent.change(fileInput(), { target: { files: [md('ok.md'), exe] } })
    expect(await screen.findByText('ok.md')).toBeInTheDocument()
    expect(screen.queryByText('virus.exe')).not.toBeInTheDocument()
    expect(screen.getByText(/Skipped 1 unsupported/)).toBeInTheDocument()
  })
})

describe('UploadPage — sequential compile', () => {
  it('uploads every file, in file order, and marks them done', async () => {
    renderUploadPage()
    fireEvent.change(fileInput(), { target: { files: [md('1.md'), md('2.md'), md('3.md')] } })
    fireEvent.click(uploadBtn())

    await waitFor(() => expect(uploadDocument).toHaveBeenCalledTimes(3))
    // File order is preserved across the sequential runner.
    expect(vi.mocked(uploadDocument).mock.calls.map((c) => (c[0] as File).name)).toEqual([
      '1.md', '2.md', '3.md',
    ])
    await waitFor(() => expect(screen.getAllByText('✓ Done')).toHaveLength(3))
  })

  it('sends the Destination as the space (personal by default)', async () => {
    renderUploadPage()
    fireEvent.change(fileInput(), { target: { files: [md('a.md')] } })
    fireEvent.click(uploadBtn())
    await waitFor(() =>
      expect(uploadDocument).toHaveBeenCalledWith(expect.any(File), { space: 'personal' }),
    )
  })

  it('isolates a failed file — the rest still compile', async () => {
    vi.mocked(uploadDocument).mockImplementation(async (file) => {
      if ((file as File).name === '2.md') throw new Error('boom')
      return { raw_document_id: 'r', workflow_id: 'w' }
    })
    renderUploadPage()
    fireEvent.change(fileInput(), { target: { files: [md('1.md'), md('2.md'), md('3.md')] } })
    fireEvent.click(uploadBtn())

    await waitFor(() => expect(screen.getByText('✗ Failed')).toBeInTheDocument())
    // 1.md and 3.md still succeeded despite 2.md failing.
    await waitFor(() => expect(screen.getAllByText('✓ Done')).toHaveLength(2))
    expect(uploadDocument).toHaveBeenCalledTimes(3)
  })
})

describe('UploadPage — session persistence', () => {
  it('rehydrates a persisted done job on mount', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'job-1', filename: 'saved.md', status: 'done', rawDocumentId: 'r1' },
      ]),
    )
    renderUploadPage()
    expect(await screen.findByText('saved.md')).toBeInTheDocument()
    expect(screen.getByText('✓ Done')).toBeInTheDocument()
    // A rehydrated done job is not re-uploaded.
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it('resumes a persisted compiling job and reaches Done', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'job-9', filename: 'inflight.md', status: 'compiling', rawDocumentId: 'r9' },
      ]),
    )
    renderUploadPage()
    expect(await screen.findByText('inflight.md')).toBeInTheDocument()
    // getIngestStatus resolves { status: 'done' } → the resumed poll marks it done.
    await waitFor(() => expect(screen.getByText('✓ Done')).toBeInTheDocument())
    expect(getIngestStatus).toHaveBeenCalledWith('r9')
    // Resume polls; it never re-uploads (no File on a rehydrated job).
    expect(uploadDocument).not.toHaveBeenCalled()
  })

  it('does not count a rehydrated no-File failed job as pending', async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'job-7', filename: 'broke.md', status: 'failed', error: 'boom' },
      ]),
    )
    renderUploadPage()
    expect(await screen.findByText('broke.md')).toBeInTheDocument()
    // No uploadable File → button reflects 0 pending and is disabled.
    expect(uploadBtn()).toHaveTextContent('Upload 0 files')
    expect(uploadBtn()).toBeDisabled()
  })
})
