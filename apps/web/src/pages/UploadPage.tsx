import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { uploadDocument, listTeams, type Team } from '../api'
import { runSequential, pollIngestStatus } from '../lib/bulkUpload'
import { loadJobs, saveJobs } from '../lib/uploadSession'
import Button from '../components/Button'
import Card from '../components/Card'
import Alert from '../components/Alert'

const MAX_FILES = 10
const ACCEPT_ATTR = '.md,.txt,.pdf,.png,.jpg,.jpeg'
const SUPPORTED_EXT = ['md', 'txt', 'pdf', 'png', 'jpg', 'jpeg']

type JobStatus = 'queued' | 'uploading' | 'compiling' | 'done' | 'failed'

interface UploadJob {
  id: string
  file?: File // absent on jobs rehydrated from sessionStorage
  filename: string
  status: JobStatus
  rawDocumentId?: string
  workflowId?: string
  error?: string
}

const STATUS_META: Record<JobStatus, { label: string; className: string }> = {
  queued: { label: '⏸ Queued', className: 'badge-neutral' },
  uploading: { label: '⏫ Uploading', className: 'badge-review' },
  compiling: { label: '⏳ Compiling', className: 'badge-review' },
  done: { label: '✓ Done', className: 'badge-published' },
  failed: { label: '✗ Failed', className: 'badge-rejected' },
}

function ext(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

let _seq = 0
function nextJobId(): string {
  _seq += 1
  return `job-${_seq}`
}

export default function UploadPage() {
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Seed from sessionStorage so a refresh keeps the visible queue/history.
  const [jobs, setJobs] = useState<UploadJob[]>(() => loadJobs() as UploadJob[])
  const [destination, setDestination] = useState('personal') // 'personal' | team slug | 'org'
  const [running, setRunning] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const teams = useQuery<Team[]>({ queryKey: ['teams'], queryFn: () => listTeams() })
  const resumedRef = useRef(false)

  const patchJob = (id: string, patch: Partial<UploadJob>) =>
    setJobs((prev) => prev.map((j) => (j.id === id ? { ...j, ...patch } : j)))
  const removeJob = (id: string) => setJobs((prev) => prev.filter((j) => j.id !== id))

  // Mirror the queue into sessionStorage on every change so a refresh rehydrates it.
  useEffect(() => {
    saveJobs(jobs)
  }, [jobs])

  // On first mount only, resume polling for any job that was still compiling
  // when the page was left/refreshed.
  useEffect(() => {
    if (resumedRef.current) return
    resumedRef.current = true
    for (const job of jobs) {
      if (job.status !== 'compiling' || !job.rawDocumentId) continue
      const { id, rawDocumentId } = job
      ;(async () => {
        try {
          const final = await pollIngestStatus(rawDocumentId)
          patchJob(id, {
            status: final === 'done' ? 'done' : 'failed',
            error: final === 'done' ? undefined : 'Ingest failed — check the worker logs.',
          })
        } catch {
          patchJob(id, { status: 'failed', error: 'Ingest failed — check the worker logs.' })
        }
      })()
    }
    // Run once; `jobs` is intentionally read from the initial (rehydrated) state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** Add dropped/selected files to the queue: supported-type + ≤10 guardrails. */
  function addFiles(fileList: FileList | File[]) {
    const incoming = Array.from(fileList)
    const supported = incoming.filter((f) => SUPPORTED_EXT.includes(ext(f.name)))
    const rejected = incoming.filter((f) => !SUPPORTED_EXT.includes(ext(f.name)))
    const room = Math.max(0, MAX_FILES - jobs.length)
    const toAdd = supported.slice(0, room)
    const overflow = supported.length - toAdd.length

    const msgs: string[] = []
    if (rejected.length)
      msgs.push(`Skipped ${rejected.length} unsupported file(s): ${rejected.map((r) => r.name).join(', ')}.`)
    if (overflow > 0) msgs.push(`Max ${MAX_FILES} files — ${overflow} not added.`)
    setNotice(msgs.length ? msgs.join(' ') : null)

    if (toAdd.length) {
      setJobs((prev) => [
        ...prev,
        ...toAdd.map((file) => ({
          id: nextJobId(),
          file,
          filename: file.name,
          status: 'queued' as JobStatus,
        })),
      ])
    }
  }

  /** Compile the queue strictly one file at a time (see spec: sequential so each
   * doc links against the fully-committed prior ones). */
  async function handleUpload() {
    if (running) return
    // Only jobs with a File can be uploaded; rehydrated compiling/failed jobs
    // have no File and must not be re-uploaded (they'd double-ingest).
    const pending = jobs.filter((j) => j.status !== 'done' && j.file)
    if (pending.length === 0) return
    setRunning(true)
    setNotice(null)
    const space = destination !== 'org' ? destination : undefined

    await runSequential(pending, async (job) => {
      patchJob(job.id, { status: 'uploading', error: undefined })
      try {
        const res = await uploadDocument(job.file as File, space ? { space } : {})
        patchJob(job.id, {
          status: 'compiling',
          rawDocumentId: res.raw_document_id,
          workflowId: res.workflow_id,
        })
        const final = await pollIngestStatus(res.raw_document_id)
        patchJob(job.id, {
          status: final === 'done' ? 'done' : 'failed',
          error: final === 'done' ? undefined : 'Ingest failed — check the worker logs.',
        })
      } catch (err) {
        patchJob(job.id, {
          status: 'failed',
          error: err instanceof Error ? err.message : 'Upload failed.',
        })
      }
    })

    setRunning(false)
  }

  const destinationHint =
    destination === 'personal'
      ? 'Private to you — compiled pages are visible only to your account.'
      : destination === 'org'
        ? 'Org-wide — visible to everyone in the organization (requires org editor).'
        : 'Visible to members of this team.'

  const doneCount = jobs.filter((j) => j.status === 'done').length
  // Only jobs with a File are uploadable (matches handleUpload); rehydrated
  // compiling/failed jobs have no File and must not enable/count for upload.
  const pendingCount = jobs.filter((j) => j.status !== 'done' && j.file).length

  return (
    <main className="stack">
      <h1>Upload Documents</h1>

      <Card>
        <div className="stack">
          <div>
            <label htmlFor="destination-input" className="meta">Destination</label>
            <br />
            <select
              id="destination-input"
              className="input"
              value={destination}
              disabled={running}
              onChange={(e) => setDestination(e.target.value)}
            >
              <option value="personal">My Space (personal)</option>
              {(teams.data ?? []).map((t) => (
                <option key={t.slug} value={t.slug}>{t.name}</option>
              ))}
              <option value="org">Organization (org-wide)</option>
            </select>
            <p className="meta" style={{ marginTop: 'var(--space-2)' }}>{destinationHint}</p>
          </div>

          <div
            className={`dropzone${dragOver ? ' dropzone-active' : ''}`}
            role="button"
            tabIndex={0}
            aria-label="Drop files here or click to choose files"
            onClick={() => !running && fileInputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !running) fileInputRef.current?.click()
            }}
            onDragOver={(e) => {
              e.preventDefault()
              if (!running) setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragOver(false)
              if (!running && e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
            }}
          >
            <p><strong>Drop files here</strong> or <span className="link-like">choose files</span></p>
            <p className="meta">
              Up to {MAX_FILES} files · .md, .txt, .pdf, .png, .jpg — compiled one
              at a time so each links against the ones before it.
            </p>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={ACCEPT_ATTR}
              aria-label="Choose files"
              style={{ display: 'none' }}
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files)
                e.target.value = ''
              }}
            />
          </div>

          {notice && <Alert>{notice}</Alert>}

          {jobs.length > 0 && (
            <div className="stack" role="list" aria-label="Upload queue">
              {jobs.map((job) => (
                <div
                  key={job.id}
                  role="listitem"
                  className="card"
                  style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}
                >
                  <span className={`badge ${STATUS_META[job.status].className}`}>
                    {STATUS_META[job.status].label}
                  </span>
                  <strong>{job.filename}</strong>
                  {job.error && <span className="meta">{job.error}</span>}
                  {job.status === 'done' && (
                    <Link className="meta" to="/items" style={{ marginLeft: 'auto' }}>View items →</Link>
                  )}
                  {!running && job.status === 'queued' && (
                    <button
                      type="button"
                      className="btn btn-ghost"
                      style={{ padding: '0 6px', marginLeft: 'auto' }}
                      onClick={() => removeJob(job.id)}
                    >
                      remove
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
            <Button
              type="button"
              variant="primary"
              disabled={running || pendingCount === 0}
              onClick={handleUpload}
            >
              {running
                ? `Compiling… (${doneCount}/${jobs.length})`
                : `Upload ${pendingCount} file${pendingCount !== 1 ? 's' : ''}`}
            </Button>
            {!running && jobs.length > 0 && (
              <Button variant="ghost" onClick={() => { setJobs([]); setNotice(null) }}>Clear</Button>
            )}
          </div>
        </div>
      </Card>

      {jobs.some((j) => j.status === 'done') && (
        <p className="meta">
          Compiled pages appear in <Link to="/items">Items</Link>; cost per file
          is on <Link to="/history">Upload history</Link>.
        </p>
      )}
    </main>
  )
}
