import { describe, expect, it } from 'vitest'
import type { ResearchPerson } from '../api/types'
import { groupPeople, isEmail, safeHref, stepKey } from './research'

function person(id: string, group: ResearchPerson['group']): ResearchPerson {
  return {
    id,
    name: id,
    role: 'Role',
    group,
    why: '',
    profile_url: null,
    source_url: 'https://a.example',
  }
}

describe('stepKey', () => {
  it('names a search step by its topic', () => {
    expect(stepKey({ type: 'progress', step: 'search', status: 'done', topic: 'team' })).toBe(
      'search:team',
    )
  })

  it('returns the step name for the other steps', () => {
    expect(stepKey({ type: 'progress', step: 'extract', status: 'done' })).toBe('extract')
  })
})

describe('safeHref', () => {
  it('keeps an https link', () => {
    expect(safeHref('https://a.example')).toBe('https://a.example')
  })

  it.each(['javascript:alert(1)', 'mailto:x@y.example', null])('rejects %s', (url) => {
    expect(safeHref(url)).toBeNull()
  })
})

describe('isEmail', () => {
  it('accepts an address', () => {
    expect(isEmail('jobs@acme.example')).toBe(true)
  })

  it('rejects text that is not an address', () => {
    expect(isEmail('not an email')).toBe(false)
  })
})

describe('groupPeople', () => {
  it('returns the groups in order and leaves out empty ones', () => {
    const groups = groupPeople([
      person('p1', 'peer'),
      person('p2', 'posting_owner'),
      person('p3', 'peer'),
    ])
    expect(groups.map((entry) => entry.group)).toEqual(['posting_owner', 'peer'])
    expect(groups[1].people.map((item) => item.id)).toEqual(['p1', 'p3'])
  })
})
