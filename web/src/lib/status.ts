import type { SystemStatus } from './api'

/**
 * The guarantees the agent is not currently providing, most consequential first.
 *
 * `healthy` is a single boolean, which makes a degraded agent look identical whether the
 * reasoning model is missing or the sandbox is running code outside a container. The badge
 * says which, so it reads as a partial capability rather than a failure.
 */
export function limitingFactors(status: SystemStatus): string[] {
  const factors: string[] = []
  if (!status.llm_ready) factors.push('LLM')
  if (!status.hindsight_ready) factors.push('memory')
  if (!status.repo_present) factors.push('repository')
  if (status.sandbox_backend !== 'docker') factors.push('sandbox')
  return factors
}

/** Uppercase fragment for the status strip, e.g. `SANDBOX`. Empty when nothing is limited. */
export function degradationLabel(status: SystemStatus): string {
  return limitingFactors(status)
    .map((factor) => factor.toUpperCase())
    .join(' + ')
}

/**
 * Why the agent is degraded, as one sentence.
 *
 * Prefers a warning (something went wrong) over the sandbox's own explanation (something is
 * switched off or unavailable by design), and never falls back to "ready for work" while a
 * guarantee is missing — that pairing is what made the badge look broken.
 */
export function degradationReason(status: SystemStatus): string {
  if (status.warnings.length > 0) return status.warnings[0]
  if (status.sandbox_backend !== 'docker' && status.sandbox_detail) return status.sandbox_detail
  if (status.healthy) return 'Idle, ready for work'
  return 'Running with reduced capability'
}
