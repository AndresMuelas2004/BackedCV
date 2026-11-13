import { describe, expect, it } from 'vitest'
import type { AnalysisReport } from '../api/types'
import { buildPriorities } from './priorities'

interface Row {
  id: string
  label: string
  status: 'met' | 'partial' | 'missing' | 'unknown'
  importance?: 'required' | 'preferred'
  category?: string
  knockout?: string | null
  question?: string | null
  pointsLost?: number
}

// The smallest report buildPriorities reads: one requirement, assessment and score row per Row.
function report(
  rows: Row[],
  answers: Record<string, boolean> = {},
  warnings: object[] = [],
  statements: Record<string, string> = {},
): AnalysisReport {
  const value = {
    hidden_risks: [],
    screening_flags: [],
    parse_warnings: warnings,
    excluded_ids: [],
    recency: {},
    cv: null,
    facts: { answers, statements },
    job: {
      requirements: rows.map((row) => ({
        id: row.id,
        label: row.label,
        quote: `We ask for ${row.label}.`,
        importance: row.importance ?? 'required',
        category: row.category ?? 'hard_skill',
        knockout_type: row.knockout ?? null,
        min_years: null,
      })),
    },
    assessments: Object.fromEntries(
      rows.map((row) => [
        row.id,
        {
          requirement_id: row.id,
          status: row.status,
          evidence: [],
          question: row.question ?? null,
          years_check: null,
        },
      ]),
    ),
    score: {
      contributions: rows.map((row) => ({ requirement_id: row.id, points_lost: row.pointsLost ?? 0 })),
    },
  }
  return value as unknown as AnalysisReport
}

describe('buildPriorities', () => {
  it('lists nothing for a requirement the CV meets', () => {
    expect(buildPriorities(report([{ id: 'R01', label: 'Python', status: 'met' }]))).toEqual([])
  })

  it('calls a missing must-have a serious gap and a missing bonus worth improving', () => {
    const items = buildPriorities(
      report([
        { id: 'R01', label: 'dbt', status: 'missing', importance: 'preferred' },
        { id: 'R02', label: 'Kubernetes', status: 'missing' },
      ]),
    )

    expect(items.map((item) => [item.key, item.tier])).toEqual([
      ['req-R02', 'serious'],
      ['req-R01', 'improve'],
    ])
    expect(items[0].title).toBe('Kubernetes: not in your CV')
    expect(items[1].tag).toBe('Nice to have')
  })

  it('puts an open knockout question first, and a No before it', () => {
    const rows: Row[] = [
      { id: 'R01', label: 'Kubernetes', status: 'missing', pointsLost: 20 },
      {
        id: 'R02',
        label: 'US work authorization',
        status: 'unknown',
        category: 'work_authorization',
        knockout: 'work_authorization',
        question: 'Are you authorized to work in the US?',
      },
      {
        id: 'R03',
        label: 'On-site in Austin',
        status: 'unknown',
        category: 'location',
        knockout: 'location',
        question: 'Can you work from Austin?',
      },
    ]

    const open = buildPriorities(report(rows))
    const answered = buildPriorities(report(rows, { R03: false }))

    expect(open.map((item) => item.key)).toEqual(['req-R02', 'req-R03', 'req-R01'])
    expect(open[0].tier).toBe('rule_out')
    expect(open[0].tag).toBe('Legal requirement · answer above')
    expect(answered[0].key).toBe('req-R03')
    expect(answered[0].answeredNo).toBe(true)
    expect(answered[0].tag).toBe('Location · you answered No')
  })

  it('orders the gaps of one tier by the points they cost', () => {
    const items = buildPriorities(
      report([
        { id: 'R01', label: 'SQL', status: 'missing', pointsLost: 5 },
        { id: 'R02', label: 'Python', status: 'missing', pointsLost: 12 },
      ]),
    )

    expect(items.map((item) => item.key)).toEqual(['req-R02', 'req-R01'])
  })

  it('adds problems in how the CV reads, but not plain tips', () => {
    const items = buildPriorities(
      report([], {}, [
        { code: 'two_columns', severity: 'warning', message: 'This PDF has two columns.', line_ids: [] },
        { code: 'tip', severity: 'info', message: 'Add a summary.', line_ids: [] },
      ]),
    )

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({ key: 'parse-0', tier: 'improve', tag: 'How your CV reads' })
  })

  it('lets the candidate speak for a missing skill, but not for a screening question', () => {
    const items = buildPriorities(
      report([
        { id: 'R01', label: 'Kubernetes', status: 'missing' },
        {
          id: 'R02',
          label: 'US work authorization',
          status: 'unknown',
          category: 'work_authorization',
          knockout: 'work_authorization',
          question: 'Are you authorized to work in the US?',
        },
        { id: 'R03', label: 'Bachelor degree', status: 'missing', category: 'education' },
      ]),
    )
    const byKey = new Map(items.map((item) => [item.key, item]))

    expect(byKey.get('req-R01')?.canTell).toBe(true)
    expect(byKey.get('req-R02')?.canTell).toBe(false)
    expect(byKey.get('req-R03')?.canTell).toBe(false)
  })

  it('shows what the candidate told us on the item', () => {
    const [item] = buildPriorities(
      report([{ id: 'R01', label: 'Kubernetes', status: 'missing' }], {}, [], {
        R01: 'I ran our API on Kubernetes at Acme.',
      }),
    )

    expect(item.statement).toBe('I ran our API on Kubernetes at Acme.')
    expect(item.tag).toBe('Must-have skill · you told us')
    expect(item.action).toContain('Improve my CV')
  })
})
