export default function Skeleton({ width = '100%' }: { width?: string }) {
  return <div className="skeleton" style={{ width }} aria-hidden="true" />
}
