import { ChevronLeft, ChevronRight } from 'lucide-react'
import { type KeyboardEvent, useState } from 'react'

import {
  SCREENSHOT_BASE,
  SCREENSHOT_FALLBACK_BASE,
  SCREENSHOTS,
  type Screenshot,
} from '../lib/site'

/**
 * The dashboard screenshots, as a slideshow.
 *
 * Two things drive the design. First, weight: only the slide on screen is in the DOM, so the
 * page loads one image rather than six (`loading="lazy"` for everything after the first).
 * Second, honesty: a screenshot that cannot be loaded is dropped rather than shown broken —
 * this deployment may not carry the binaries at all, which is why the source repository is
 * tried as a second source and the slideshow can end up empty and say so.
 */

function sourcesFor(slide: Screenshot): string[] {
  const local = `${SCREENSHOT_BASE}/${slide.name}.webp`
  const remote = SCREENSHOT_FALLBACK_BASE
    ? `${SCREENSHOT_FALLBACK_BASE}/${slide.name}.webp`
    : null
  return remote && remote !== local ? [local, remote] : [local]
}

export function ScreenshotSlideshow() {
  const [failed, setFailed] = useState<string[]>([])
  const [index, setIndex] = useState(0)
  // Which source of the current slide is on screen. Reset whenever the slide changes.
  const [attempt, setAttempt] = useState(0)

  const slides = SCREENSHOTS.filter((slide) => !failed.includes(slide.name))
  const position = slides.length === 0 ? 0 : Math.min(index, slides.length - 1)
  const current = slides[position] ?? null

  const go = (delta: number) => {
    if (slides.length === 0) return
    setAttempt(0)
    setIndex((value) => (Math.min(value, slides.length - 1) + delta + slides.length) % slides.length)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      go(-1)
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      go(1)
    }
  }

  /** Fall through to the next source; when there is none left, retire the slide. */
  const onImageError = () => {
    if (!current) return
    if (attempt + 1 < sourcesFor(current).length) {
      setAttempt(attempt + 1)
      return
    }
    setAttempt(0)
    setFailed((list) => (list.includes(current.name) ? list : [...list, current.name]))
  }

  if (!current) {
    return (
      <div className="border-2 border-ink bg-paper px-5 py-6">
        <h3 className="text-label font-black uppercase tracking-widest text-ink">
          Screenshots unavailable
        </h3>
        <p className="mt-2 max-w-2xl text-meta text-status-idle">
          This deployment does not serve the screenshots and the source repository could not be
          reached, so none are shown here rather than one broken image per slide. Everything the
          panels on this page report is read from the deployment itself.
        </p>
      </div>
    )
  }

  const candidates = sourcesFor(current)

  return (
    <section
      aria-label="Dashboard screenshots"
      aria-roledescription="carousel"
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="border-2 border-ink bg-paper"
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b-2 border-ink px-5 py-3">
        <h3 className="font-mono text-micro font-bold uppercase tracking-wide text-ink">
          {current.route}
        </h3>
        <span aria-live="polite" className="font-mono text-micro text-status-idle">
          {String(position + 1).padStart(2, '0')} / {String(slides.length).padStart(2, '0')}
        </span>
      </header>

      <div
        role="group"
        aria-roledescription="slide"
        aria-label={`${position + 1} of ${slides.length}: ${current.title}`}
        className="bg-muted p-4 swiss-grid-pattern sm:p-6"
      >
        <img
          key={`${current.name}-${attempt}`}
          src={candidates[attempt] ?? candidates[0]}
          alt={current.alt}
          width={current.width}
          height={current.height}
          loading={position === 0 ? 'eager' : 'lazy'}
          decoding="async"
          onError={onImageError}
          className="block h-auto w-full animate-fade-rise border-2 border-ink bg-paper"
        />
      </div>

      <div className="border-t-2 border-ink px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-x-8 gap-y-4">
          <div className="max-w-2xl">
            <h4 className="text-meta font-black uppercase tracking-widest text-ink">
              {current.title}
            </h4>
            <p className="mt-1.5 text-meta text-status-idle">{current.caption}</p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => go(-1)}
              aria-label="Previous screenshot"
              className="inline-flex h-9 w-9 items-center justify-center border-2 border-ink bg-paper text-ink transition-colors duration-150 ease-linear hover:bg-ink hover:text-paper"
            >
              <ChevronLeft size={15} strokeWidth={2.5} aria-hidden />
            </button>
            <button
              type="button"
              onClick={() => go(1)}
              aria-label="Next screenshot"
              className="inline-flex h-9 w-9 items-center justify-center border-2 border-ink bg-paper text-ink transition-colors duration-150 ease-linear hover:bg-ink hover:text-paper"
            >
              <ChevronRight size={15} strokeWidth={2.5} aria-hidden />
            </button>
          </div>
        </div>
      </div>

      <ul className="flex flex-wrap gap-px border-t-2 border-ink bg-hair">
        {slides.map((slide, slideIndex) => (
          <li key={slide.name}>
            <button
              type="button"
              onClick={() => {
                setAttempt(0)
                setIndex(slideIndex)
              }}
              aria-current={slideIndex === position ? 'true' : undefined}
              className={`px-4 py-2 text-label font-black uppercase tracking-widest transition-colors duration-150 ease-linear ${
                slideIndex === position
                  ? 'bg-ink text-paper'
                  : 'bg-paper text-status-idle hover:bg-muted hover:text-ink'
              }`}
            >
              {String(slideIndex + 1).padStart(2, '0')} {slide.title}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
