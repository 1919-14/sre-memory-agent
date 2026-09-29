#!/usr/bin/env node
/**
 * Capture screenshots of the running dashboard, for the landing page.
 *
 *   npm run build && python ../scripts/serve.py          # in another shell
 *   node scripts/capture-screenshots.mjs --out ../screenshots
 *   node scripts/capture-screenshots.mjs --views repairs --out ../screenshots
 *
 * The landing page's product grid shows the real interface, so its images are produced here
 * from a real deployment rather than mocked up. The script drives an installed Chrome over the
 * DevTools Protocol using Node's built-in WebSocket and fetch — there is no puppeteer
 * dependency to keep current, and nothing here is needed at runtime.
 *
 * Chrome is launched with `--remote-debugging-port=0`, so the port is chosen by the OS and read
 * back from the profile directory: nothing else on the machine has to be idle for this to work.
 */

import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))

const argv = process.argv.slice(2)
const arg = (name, fallback) => {
  const index = argv.indexOf(`--${name}`)
  return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback
}

const BASE = arg('base', process.env.SITE_URL ?? 'http://127.0.0.1:8000')
const OUT_DIR = resolve(HERE, '..', arg('out', 'public/screenshots'))
const WIDTH = Number(arg('width', '1440'))
const HEIGHT = Number(arg('height', '900'))
const SETTLE_MS = Number(arg('settle', '4500'))
// `--views incident,repairs` captures a subset. Views not named are skipped, so a single
// screen can be re-shot without rewriting the others.
const ONLY = arg('views', '')
  .split(',')
  .map((name) => name.trim())
  .filter(Boolean)

const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  join(process.env.LOCALAPPDATA ?? '', 'Google/Chrome/Application/chrome.exe'),
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean)

/** The dashboard views worth showing, in the order the landing page presents them. */
const VIEWS = [
  { name: 'overview', path: () => '/app', settle: SETTLE_MS },
  { name: 'incidents', path: () => '/app/incidents', settle: SETTLE_MS },
  { name: 'incident', path: (id) => `/app/incidents/${id}`, settle: SETTLE_MS, scroll: 380 },
  { name: 'memory', path: () => '/app/memory', settle: SETTLE_MS },
  { name: 'repairs', path: () => '/app/repairs', settle: SETTLE_MS, scroll: 300 },
  { name: 'review', path: () => '/app/review', settle: SETTLE_MS },
  { name: 'sandbox', path: () => '/app/sandbox', settle: SETTLE_MS, scroll: 260 },
  { name: 'learning', path: () => '/app/learning', settle: SETTLE_MS },
]

// ── a minimal DevTools Protocol client ────────────────────────

class Cdp {
  constructor(socket) {
    this.socket = socket
    this.nextId = 1
    this.pending = new Map()
    this.listeners = new Map()
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(event.data)
      if (message.id && this.pending.has(message.id)) {
        const { resolve: onOk, reject } = this.pending.get(message.id)
        this.pending.delete(message.id)
        if (message.error) reject(new Error(`${message.error.message} (${message.error.code})`))
        else onOk(message.result ?? {})
        return
      }
      for (const listener of this.listeners.get(message.method) ?? []) listener(message.params ?? {})
    })
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++
    const payload = { id, method, params }
    if (sessionId) payload.sessionId = sessionId
    this.socket.send(JSON.stringify(payload))
    return new Promise((onOk, reject) => this.pending.set(id, { resolve: onOk, reject }))
  }

  /** Resolve once `method` has fired, or reject after `timeoutMs`. */
  once(method, timeoutMs) {
    return new Promise((onOk, reject) => {
      const timer = setTimeout(() => reject(new Error(`timed out waiting for ${method}`)), timeoutMs)
      const listener = (params) => {
        clearTimeout(timer)
        const list = this.listeners.get(method) ?? []
        this.listeners.set(
          method,
          list.filter((entry) => entry !== listener),
        )
        onOk(params)
      }
      this.listeners.set(method, [...(this.listeners.get(method) ?? []), listener])
    })
  }
}

const sleep = (ms) => new Promise((onOk) => setTimeout(onOk, ms))

// ── run ───────────────────────────────────────────────────────

async function findChrome() {
  for (const candidate of CHROME_CANDIDATES) {
    if (candidate && existsSync(candidate)) return candidate
  }
  throw new Error(
    `Chrome was not found. Set CHROME_PATH, or install Chrome in one of:\n  ${CHROME_CANDIDATES.join('\n  ')}`,
  )
}

/** The most instructive incident to show: a recovered one with more than one attempt. */
async function pickIncident() {
  const response = await fetch(`${BASE}/api/incidents?limit=20`)
  if (!response.ok) throw new Error(`GET /api/incidents → HTTP ${response.status}`)
  const { incidents } = await response.json()
  const interesting = incidents.find(
    (incident) => incident.outcome === 'recovered' && (incident.attempts ?? 0) > 1,
  )
  return (interesting ?? incidents[0])?.id ?? null
}

async function main() {
  const chrome = await findChrome()
  const profile = await mkdtemp(join(tmpdir(), 'sre-shots-'))
  await mkdir(OUT_DIR, { recursive: true })

  const child = spawn(
    chrome,
    [
      '--headless=new',
      '--disable-gpu',
      '--hide-scrollbars',
      '--no-first-run',
      '--no-default-browser-check',
      '--disable-extensions',
      '--disable-background-networking',
      `--user-data-dir=${profile}`,
      '--remote-debugging-port=0',
      'about:blank',
    ],
    { stdio: 'ignore' },
  )

  try {
    const portFile = join(profile, 'DevToolsActivePort')
    let port = null
    for (let attempt = 0; attempt < 100 && port === null; attempt += 1) {
      await sleep(100)
      if (!existsSync(portFile)) continue
      const [first] = (await readFile(portFile, 'utf8')).split('\n')
      port = Number(first)
    }
    if (!port) throw new Error('Chrome did not report a debugging port')

    const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()
    const socket = new WebSocket(version.webSocketDebuggerUrl)
    await new Promise((onOk, reject) => {
      socket.addEventListener('open', onOk, { once: true })
      socket.addEventListener('error', () => reject(new Error('devtools socket failed')), {
        once: true,
      })
    })

    const cdp = new Cdp(socket)
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' })
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true })

    const send = (method, params) => cdp.send(method, params, sessionId)
    await send('Page.enable')
    await send('Emulation.setDeviceMetricsOverride', {
      width: WIDTH,
      height: HEIGHT,
      deviceScaleFactor: 1,
      mobile: false,
    })

    /**
     * Wait until the page's <main> actually has content.
     *
     * A fixed sleep is the wrong instrument: it either misses a page that is still fetching or
     * wastes time on one that rendered immediately. The budget is therefore a ceiling, not a
     * duration — and a page that never fills in is reported rather than captured silently.
     */
    const waitForContent = async (budgetMs) => {
      const deadline = Date.now() + budgetMs
      let chars = 0
      while (Date.now() < deadline) {
        await sleep(250)
        const { result } = await send('Runtime.evaluate', {
          expression:
            '(document.querySelector("main")?.innerText ?? "").replace(/\\s+/g, " ").trim().length',
          returnByValue: true,
        })
        chars = Number(result.value ?? 0)
        if (chars > 800) break
      }
      // The shell is already painted by this point; give fonts and the last layout pass a
      // moment so the capture is not of a half-drawn frame.
      await sleep(250)
      return chars
    }

    const unknown = ONLY.filter((name) => !VIEWS.some((view) => view.name === name))
    if (unknown.length) throw new Error(`unknown view(s): ${unknown.join(', ')}`)
    const views = ONLY.length ? VIEWS.filter((view) => ONLY.includes(view.name)) : VIEWS

    const incidentId = await pickIncident()
    if (!incidentId) console.warn('no incidents recorded — the incident view will show its empty state')

    const results = []
    for (const view of views) {
      const url = `${BASE}${view.path(incidentId)}`
      const loaded = cdp.once('Page.loadEventFired', 20_000)
      await send('Page.navigate', { url })
      await loaded
      const mainChars = await waitForContent(view.settle ?? SETTLE_MS)

      if (view.scroll) {
        await send('Runtime.evaluate', {
          expression: `window.scrollTo(0, ${view.scroll})`,
          awaitPromise: true,
        })
        await sleep(400)
      }

      const { data } = await send('Page.captureScreenshot', { format: 'png' })
      const file = join(OUT_DIR, `${view.name}.png`)
      await writeFile(file, Buffer.from(data, 'base64'))

      // A blank capture is the failure mode worth catching: report how much of the page was
      // actually rendered, so a screenshot that says nothing shows up in the log as well as in
      // the image.
      results.push({ name: view.name, url, chars: mainChars, file })
      console.log(`${String(mainChars).padStart(6)} chars  ${view.name.padEnd(10)} ${url}`)
    }

    console.log(`\n${results.length} screenshots written to ${OUT_DIR}`)
    const blank = results.filter((entry) => (entry.chars ?? 0) < 800)
    if (blank.length) {
      console.error(`suspiciously empty: ${blank.map((entry) => entry.name).join(', ')}`)
      process.exitCode = 1
    }

    socket.close()
  } finally {
    child.kill()
    try {
      await rm(profile, { recursive: true, force: true })
    } catch (error) {
      // Chrome can still hold the profile's lock file for a moment after it is signalled.
      // Leaving a temporary directory behind is not a reason to fail an otherwise good run.
      console.warn(`could not remove ${profile} (${error.code ?? error.message})`)
    }
  }
}

await main()
