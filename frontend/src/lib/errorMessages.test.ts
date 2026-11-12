import { describe, expect, it } from 'vitest'
import { describeFailure } from './errorMessages'

describe('describeFailure', () => {
  it('uses the plain text of a known code and keeps the server detail', () => {
    const failure = describeFailure({
      code: 'rate_limited',
      title: 'Too many requests from this network.',
      detail: 'Try again in 5 minutes.',
    })

    expect(failure).toEqual({
      message: 'You have made too many checks in the last hour.',
      next: 'Wait for the time shown below, then try again.',
      detail: 'Try again in 5 minutes.',
    })
  })

  it('falls back to the server title for a code it does not know', () => {
    const failure = describeFailure({ code: 'brand_new', title: 'Something new.', detail: '' })

    expect(failure).toEqual({ message: 'Something new.', next: null, detail: '' })
  })

  it('says so when the model is not available', () => {
    const failure = describeFailure({ code: 'model_unavailable', title: 'x', detail: '' })

    expect(failure.message).toContain('not available')
  })
})
