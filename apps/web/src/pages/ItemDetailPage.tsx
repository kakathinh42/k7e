import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getItem, type ItemDetail } from '../api'
import StatusBadge from '../components/StatusBadge'
import Markdown from '../components/Markdown'
import ItemRail from '../components/ItemRail'
import Skeleton from '../components/Skeleton'
import Alert from '../components/Alert'
import { buildProvenanceSteps } from '../lib/pipeline'

export default function ItemDetailPage() {
  const { slug } = useParams<{ slug: string }>()

  const { data: item, isLoading, error } = useQuery<ItemDetail>({
    queryKey: ['item', slug],
    queryFn: () => getItem(slug!),
    enabled: Boolean(slug),
    retry: (failureCount, err) =>
      err instanceof Error && err.message.startsWith('HTTP 404') ? false : failureCount < 2,
  })

  if (!slug) {
    return <main><h1>Item Not Found</h1><p className="meta">No slug provided.</p></main>
  }
  if (isLoading) {
    return (
      <main className="stack">
        <Skeleton width="40%" />
        <div className="card"><Skeleton width="80%" /></div>
      </main>
    )
  }
  if (error || !item) {
    const is404 = error instanceof Error && error.message.startsWith('HTTP 404')
    return (
      <main>
        <h1>{is404 ? 'Item Not Found' : 'Error'}</h1>
        <Alert>
          {is404
            ? `No item found with slug “${slug}”.`
            : error instanceof Error ? error.message : 'Unknown error'}
        </Alert>
      </main>
    )
  }

  return (
    <main className="stack">
      <div className="item-head">
        <h1>{item.title}</h1>
        <StatusBadge status={item.status} />
      </div>
      <p className="prov-line">
        v{item.version} · {item.model_id} · updated {new Date(item.updated_at).toLocaleString()}
      </p>

      {(item.domain || item.tags.length > 0) && (
        <div className="facet-group" aria-label="Classification">
          {item.domain && (
            <Link className="chip" to={`/items?domain=${encodeURIComponent(item.domain)}`}>
              {item.domain}
            </Link>
          )}
          {item.tags.map((t) => (
            <Link className="chip" to={`/items?tag=${encodeURIComponent(t)}`} key={t}>
              {t}
            </Link>
          ))}
        </div>
      )}

      <div className="item-cols">
        <div className="item-main">
          <Markdown>{item.markdown_body}</Markdown>
        </div>
        <ItemRail steps={buildProvenanceSteps(item)} sources={item.sources} />
      </div>
    </main>
  )
}
