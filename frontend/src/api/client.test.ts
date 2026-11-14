import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  cvDownloadUrl,
  runAnalysis,
  runOptimize,
  type AnalysisEvent,
  type OptimizeEvent,
} from './client'

// A streamed response whose body arrives in the given chunks.
function sse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

function answerWith(response: Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => response),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

const INPUT = { cv: { text: 'Jane Doe' }, jobText: 'A posting' }

describe('runAnalysis', () => {
  it('reads the events of a stream, also when one is split across chunks', async () => {
    answerWith(
      sse([
        'event: created\ndata: {"analysis_id":"abc"}\n\n',
        'event: progress\ndata: {"type":"progress","step":"prepare_job",',
        '"status":"done","requirements":2}\n\nevent: report\r\ndata: {"analysis_id":"abc"}\r\n\r\n',
      ]),
    )
    const events: AnalysisEvent[] = []

    await runAnalysis(INPUT, (event) => {
      events.push(event)
    })

    expect(events.map((event) => event.type)).toEqual(['created', 'progress', 'report'])
    expect(events[0]).toEqual({ type: 'created', analysisId: 'abc' })
  })

  it('passes an error event on with its body', async () => {
    const error = { code: 'model_busy', title: 'The AI model is busy right now.', detail: '' }
    answerWith(sse([`event: error\ndata: ${JSON.stringify(error)}\n\n`]))
    const events: AnalysisEvent[] = []

    await runAnalysis(INPUT, (event) => {
      events.push(event)
    })

    expect(events).toEqual([{ type: 'error', error }])
  })

  it('throws when the stream closes before the report', async () => {
    answerWith(sse(['event: created\ndata: {"analysis_id":"abc"}\n\n']))

    await expect(runAnalysis(INPUT, () => undefined)).rejects.toMatchObject({
      code: 'stream_incomplete',
    })
  })

  it('throws the JSON error of a refused request', async () => {
    const body = {
      code: 'rate_limited',
      title: 'Too many requests from this network.',
      detail: 'Try again in 5 minutes.',
    }
    answerWith(new Response(JSON.stringify(body), { status: 429 }))

    const failure = runAnalysis(INPUT, () => undefined)

    await expect(failure).rejects.toBeInstanceOf(ApiError)
    await expect(failure).rejects.toMatchObject({ status: 429, code: 'rate_limited' })
  })
})

describe('runOptimize', () => {
  it('ends with the suggestions event', async () => {
    answerWith(
      sse([
        'event: progress\ndata: {"type":"progress","step":"suggest","status":"started"}\n\n' +
          'event: suggestions\ndata: {"analysis_id":"abc"}\n\n',
      ]),
    )
    const events: OptimizeEvent[] = []

    await runOptimize('abc', (event) => {
      events.push(event)
    })

    expect(events.map((event) => event.type)).toEqual(['progress', 'suggestions'])
  })
})

describe('cvDownloadUrl', () => {
  it('has no query when no limit or format is given', () => {
    expect(cvDownloadUrl('a1', 'pdf')).toBe('/api/analyses/a1/cv.pdf')
  })

  it('adds the page limit', () => {
    expect(cvDownloadUrl('a1', 'pdf', 1)).toBe('/api/analyses/a1/cv.pdf?max_pages=1')
  })

  it('adds the format', () => {
    expect(cvDownloadUrl('a1', 'docx', null, 'standard')).toBe(
      '/api/analyses/a1/cv.docx?style=standard',
    )
  })

  it('adds both, page limit first', () => {
    expect(cvDownloadUrl('a1', 'pdf', 2, 'original')).toBe(
      '/api/analyses/a1/cv.pdf?max_pages=2&style=original',
    )
  })
})
