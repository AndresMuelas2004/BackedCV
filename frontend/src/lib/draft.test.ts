import { describe, expect, it } from 'vitest'
import { EMPTY_DRAFT, MIN_JOB_CHARS, fileProblem, findProblems, toAnalysisInput } from './draft'

const POSTING = 'x'.repeat(MIN_JOB_CHARS)

function file(name: string, size: number): File {
  return new File([new Uint8Array(size)], name)
}

describe('fileProblem', () => {
  it('accepts a PDF or DOCX within the size limit', () => {
    expect(fileProblem(file('cv.pdf', 10))).toBeNull()
    expect(fileProblem(file('CV.DOCX', 10))).toBeNull()
  })

  it('refuses other types, empty files and files over 4 MB', () => {
    expect(fileProblem(file('cv.txt', 10))).toBe('Upload a PDF or DOCX file.')
    expect(fileProblem(file('cv.pdf', 0))).toBe('This file is empty.')
    expect(fileProblem(file('cv.pdf', 4 * 1024 * 1024 + 1))).toBe('This file is larger than 4 MB.')
  })
})

describe('findProblems', () => {
  it('asks for a CV and a posting when both are missing', () => {
    const problems = findProblems(EMPTY_DRAFT)

    expect(problems.cv).not.toBeNull()
    expect(problems.job).toBe('Paste the job posting you want to check.')
  })

  it('refuses a posting that is too short or too long', () => {
    expect(findProblems({ ...EMPTY_DRAFT, jobText: 'short' }).job).toContain('too short')
    expect(findProblems({ ...EMPTY_DRAFT, jobText: 'x'.repeat(20_001) }).job).toContain('limited to')
  })

  it('finds no problem in a full draft', () => {
    const draft = { cvMode: 'text' as const, cvFile: null, cvText: 'Jane Doe', jobText: POSTING }

    expect(findProblems(draft)).toEqual({ cv: null, job: null })
  })
})

describe('toAnalysisInput', () => {
  it('sends pasted CV text as it is and trims the posting', () => {
    const draft = { cvMode: 'text' as const, cvFile: null, cvText: ' Jane ', jobText: `  ${POSTING}\n` }

    expect(toAnalysisInput(draft)).toEqual({ cv: { text: ' Jane ' }, jobText: POSTING })
  })

  it('returns nothing in file mode without a file', () => {
    expect(toAnalysisInput({ ...EMPTY_DRAFT, jobText: POSTING })).toBeNull()
  })
})
