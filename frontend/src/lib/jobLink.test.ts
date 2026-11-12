import { describe, expect, it } from 'vitest'
import { isLinkedInJobLink } from './jobLink'

describe('isLinkedInJobLink', () => {
  it.each([
    'https://www.linkedin.com/jobs/view/4471986391/',
    'linkedin.com/jobs/view/python-developer-at-acme-4471986391?refId=abc',
    'https://es.linkedin.com/jobs/view/4471986391',
    'https://www.linkedin.com/jobs/search/?currentJobId=4471986391&keywords=python',
    '  https://www.linkedin.com/jobs/view/4471986391  ',
  ])('accepts %s', (link) => {
    expect(isLinkedInJobLink(link)).toBe(true)
  })

  it.each([
    '',
    'https://www.linkedin.com/in/someone',
    'https://www.linkedin.com/jobs/',
    'https://notlinkedin.com/jobs/view/4471986391',
    'https://example.com/?next=linkedin.com/jobs/view/4471986391',
    'See https://www.linkedin.com/jobs/view/4471986391 for details',
    'We need a Python developer with 5 years of experience.',
  ])('rejects %s', (text) => {
    expect(isLinkedInJobLink(text)).toBe(false)
  })
})
