import { describe, expect, it } from 'vitest'
import { applyProgress, initialProgress } from './progress'

describe('applyProgress', () => {
  it('marks the step of the event active and the earlier ones done', () => {
    const state = applyProgress(initialProgress(), {
      type: 'progress',
      step: 'match',
      status: 'started',
    })

    expect(state.steps).toEqual({
      prepare_cv: 'done',
      prepare_job: 'done',
      match: 'active',
      score: 'waiting',
    })
  })

  it('keeps the requirement count and the labels of the posting', () => {
    const read = applyProgress(initialProgress(), {
      type: 'progress',
      step: 'prepare_job',
      status: 'done',
      requirements: 3,
      labels: ['Python', 'SQL'],
    })
    const later = applyProgress(read, {
      type: 'progress',
      step: 'match',
      status: 'chunk_done',
      requirements: 2,
    })

    expect(read.requirements).toBe(3)
    expect(later.requirements).toBe(3)
    expect(later.labels).toEqual(['Python', 'SQL'])
  })

  it('ignores a step it does not know', () => {
    const start = initialProgress()

    expect(applyProgress(start, { type: 'progress', step: 'other' as never, status: 'done' })).toBe(
      start,
    )
  })
})
