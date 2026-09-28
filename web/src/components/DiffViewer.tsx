import { useMemo } from 'react'

import { CopyButton } from './primitives'

interface DiffLine {
  kind: 'add' | 'del' | 'context' | 'hunk' | 'meta'
  text: string
  oldNumber: number | null
  newNumber: number | null
}

/**
 * Parse a unified diff into addressable lines.
 *
 * Diff text arrives as a plain string from the backend, so line numbers are tracked here
 * rather than trusted from the payload.
 */
function parseDiff(diff: string): DiffLine[] {
  const lines: DiffLine[] = []
  let oldNumber = 0
  let newNumber = 0

  for (const raw of diff.split('\n')) {
    if (raw.startsWith('@@')) {
      const match = /@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw)
      if (match) {
        oldNumber = Number(match[1])
        newNumber = Number(match[2])
      }
      lines.push({ kind: 'hunk', text: raw, oldNumber: null, newNumber: null })
      continue
    }
    if (raw.startsWith('+++') || raw.startsWith('---') || raw.startsWith('diff ') || raw.startsWith('index ')) {
      lines.push({ kind: 'meta', text: raw, oldNumber: null, newNumber: null })
      continue
    }
    if (raw.startsWith('+')) {
      lines.push({ kind: 'add', text: raw.slice(1), oldNumber: null, newNumber: newNumber })
      newNumber += 1
      continue
    }
    if (raw.startsWith('-')) {
      lines.push({ kind: 'del', text: raw.slice(1), oldNumber: oldNumber, newNumber: null })
      oldNumber += 1
      continue
    }
    lines.push({
      kind: 'context',
      text: raw.startsWith(' ') ? raw.slice(1) : raw,
      oldNumber: oldNumber || null,
      newNumber: newNumber || null,
    })
    if (oldNumber) oldNumber += 1
    if (newNumber) newNumber += 1
  }

  return lines
}

export function DiffViewer({
  diff,
  label = 'Patch',
  maxHeight = '28rem',
}: {
  diff: string
  label?: string
  maxHeight?: string
}) {
  const lines = useMemo(() => parseDiff(diff), [diff])
  const added = lines.filter((line) => line.kind === 'add').length
  const removed = lines.filter((line) => line.kind === 'del').length

  if (!diff.trim()) {
    return (
      <div className="border-2 border-hair px-4 py-3 text-meta text-status-idle">
        No diff was produced for this change.
      </div>
    )
  }

  return (
    <figure className="border-2 border-ink">
      <figcaption className="flex items-center justify-between gap-3 border-b-2 border-ink px-3 py-2">
        <div className="flex items-baseline gap-3">
          <span className="text-label font-black uppercase tracking-widest text-ink">{label}</span>
          <span className="font-mono text-micro text-status-ok">+{added}</span>
          <span className="font-mono text-micro text-status-bad">−{removed}</span>
        </div>
        <CopyButton value={diff} label={`${label} diff`} />
      </figcaption>
      <div className="code-surface overflow-auto" style={{ maxHeight }}>
        <table className="w-full border-collapse">
          <tbody>
            {lines.map((line, index) => (
              <tr
                key={index}
                className={
                  line.kind === 'add'
                    ? 'bg-[#08210F]'
                    : line.kind === 'del'
                      ? 'bg-[#2A0903]'
                      : line.kind === 'hunk'
                        ? 'bg-[#141414]'
                        : undefined
                }
              >
                <td className="w-10 select-none border-r border-white/10 px-2 text-right align-top text-white/35">
                  {line.oldNumber ?? ''}
                </td>
                <td className="w-10 select-none border-r border-white/10 px-2 text-right align-top text-white/35">
                  {line.newNumber ?? ''}
                </td>
                <td
                  className={`whitespace-pre px-3 align-top ${
                    line.kind === 'add'
                      ? 'text-[#5FD08A]'
                      : line.kind === 'del'
                        ? 'text-[#FF8A70]'
                        : line.kind === 'hunk'
                          ? 'text-[#7FB3FF]'
                          : line.kind === 'meta'
                            ? 'text-white/50'
                            : 'text-white/85'
                  }`}
                >
                  <span aria-hidden className="mr-2 select-none text-white/35">
                    {line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}
                  </span>
                  {line.text || ' '}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  )
}
