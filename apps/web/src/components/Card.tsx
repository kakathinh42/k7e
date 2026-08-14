import type { HTMLAttributes } from 'react'

/** A surface panel. Forwards `style` and any standard div attributes. */
export default function Card({ className = '', ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`.trim()} {...rest} />
}
