import PipelineStepper from './PipelineStepper'
import Sources from './Sources'
import type { Step } from '../lib/pipeline'
import type { SourceRef } from '../api'

/**
 * Sticky right-rail for the reading view: the vertical provenance stepper
 * plus compiled-from / derived-from sources. Presentational only — all data
 * is passed in by the page.
 */
export default function ItemRail({
  steps,
  sources,
}: {
  steps: Step[]
  sources: SourceRef[]
}) {
  return (
    <aside className="rail">
      <div>
        <p className="rail-label">Provenance</p>
        <div className="panel">
          <PipelineStepper steps={steps} variant="vertical" ariaLabel="Item provenance" />
        </div>
      </div>
      {sources.length > 0 && (
        <div>
          <p className="rail-label">Sources</p>
          <div className="panel">
            <Sources sources={sources} />
          </div>
        </div>
      )}
    </aside>
  )
}
