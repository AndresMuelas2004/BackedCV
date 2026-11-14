import { useEffect, useState } from 'react'
import { cvDownloadUrl, getCvLayout } from '../../api/client'
import type { AnalysisReport, BuildReport, CvLayout, CvStyle, DiffLine } from '../../api/types'
import { CitedText } from '../CitationTag'
import HowComputed from '../HowComputed'
import ScoreValue from '../review/ScoreValue'
import LineDiff from './LineDiff'
import './BuildScreen.css'

interface BuildScreenProps {
  analysis: AnalysisReport
  onStartOver: () => void
  onDelete: () => void
}

// Page limits offered for the new CV. The server tightens the text to fit, and never cuts. Without
// a limit, a CV in its own format takes the pages of the uploaded file.
function pageChoices(style: CvStyle | null): { value: number | null; label: string }[] {
  return [
    { value: null, label: style === 'original' ? 'Same as my CV' : 'Any length' },
    { value: 1, label: '1 page' },
    { value: 2, label: '2 pages' },
  ]
}

type LayoutState =
  | { status: 'loading' }
  | { status: 'ready'; layout: CvLayout }
  | { status: 'failed' }

export default function BuildScreen({ analysis, onStartOver, onDelete }: BuildScreenProps) {
  const [maxPages, setMaxPages] = useState<number | null>(null)
  // null: the server picks the format (the look of the uploaded file when it was read).
  const [style, setStyle] = useState<CvStyle | null>(null)
  const layout = useCvLayout(analysis.analysis_id, maxPages, style)
  const styles = layout.status === 'ready' ? layout.layout.styles : []
  const shownStyle: CvStyle | null = style ?? (layout.status === 'ready' ? layout.layout.style : null)
  const columns = layout.status === 'ready' ? layout.layout.columns : 1
  const report = analysis.build_report
  if (!report) {
    return (
      <section className="card" aria-labelledby="missing-title">
        <h1 id="missing-title" tabIndex={-1} data-screen-heading>
          The build report is missing.
        </h1>
        <div className="downloads">
          <button type="button" className="btn btn-secondary" onClick={onStartOver}>
            Start over
          </button>
        </div>
      </section>
    )
  }

  const coverageBefore = report.coverage_before ?? analysis.score?.coverage ?? null
  const fit = report.fit ?? analysis.score?.fit ?? null
  const fitAfter = report.fit_after ?? null
  const fitRaised = fitAfter !== null && fit !== null && fitAfter !== fit
  const titles = new Map<string, string>(
    (analysis.document?.sections ?? []).map((section): [string, string] => [section.id, section.heading]),
  )

  return (
    <div className="build">
      <section className="card build-summary" aria-labelledby="build-title">
        <p className="eyebrow">Built</p>
        <h1 id="build-title" tabIndex={-1} data-screen-heading>
          Your new CV is ready
        </h1>
        <p className="order-note">{orderNote(report.built_by)}</p>

        <section className="build-fact" aria-labelledby="coverage-title">
          <h3 id="coverage-title">Keyword coverage</h3>
          <div className="compare">
            <div className="compare-item">
              <span className="compare-label">Before</span>
              <span className="compare-value">
                <ScoreValue value={coverageBefore} />
              </span>
            </div>
            <span className="compare-arrow" aria-hidden="true">
              →
            </span>
            <div className="compare-item">
              <span className="compare-label">After</span>
              <span className="compare-value">
                <ScoreValue value={report.coverage_after} />
              </span>
            </div>
          </div>
        </section>

        <section className="build-fact" aria-labelledby="fit-title">
          <h3 id="fit-title">Fit</h3>
          {fitRaised ? (
            <>
              <div className="compare">
                <div className="compare-item">
                  <span className="compare-label">Before</span>
                  <span className="compare-value">
                    <ScoreValue value={fit} />
                  </span>
                </div>
                <span className="compare-arrow" aria-hidden="true">
                  →
                </span>
                <div className="compare-item">
                  <span className="compare-label">After</span>
                  <span className="compare-value">
                    <ScoreValue value={fitAfter} />
                  </span>
                </div>
              </div>
              <p className="screen-note">
                The lines you added show experience your old CV did not, so fit goes up.
              </p>
            </>
          ) : (
            <>
              <p>
                <span className="fit-value">
                  <ScoreValue value={fit} />
                </span>{' '}
                <span className="fit-status">(unchanged)</span>
              </p>
              <p className="screen-note">Rewording cannot add experience, so fit stays the same.</p>
            </>
          )}
        </section>

        <section className="build-fact" aria-labelledby="check-title">
          <h3 id="check-title">PDF check</h3>
          {report.roundtrip_ok === true && (
            <p className="notice notice-info">The PDF reads back correctly.</p>
          )}
          {report.roundtrip_ok === false && (
            <div className="notice notice-warn">
              <p>The PDF does not read back correctly.</p>
              {report.roundtrip_issues.length > 0 && (
                <ul className="issue-list">
                  {report.roundtrip_issues.map((issue, index) => (
                    <li key={index}>
                      <CitedText text={issue} />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {report.roundtrip_ok === null && <p className="notice">The PDF was not checked.</p>}
          {report.validation_errors.length > 0 && (
            <div className="notice notice-warn">
              <p>Some checks failed:</p>
              <ul className="issue-list">
                {report.validation_errors.map((error, index) => (
                  <li key={index}>
                    <CitedText text={error} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {styles.includes('original') && (
          <section className="build-fact" aria-labelledby="format-title">
            <h3 id="format-title">Format</h3>
            <fieldset className="page-choices">
              <legend>Build the CV in</legend>
              <label className="page-choice">
                <input
                  type="radio"
                  name="cv-style"
                  checked={shownStyle === 'original'}
                  onChange={() => setStyle('original')}
                />
                The format of my CV
              </label>
              <label className="page-choice">
                <input
                  type="radio"
                  name="cv-style"
                  checked={shownStyle === 'standard'}
                  onChange={() => setStyle('standard')}
                />
                A plain one-column template
              </label>
            </fieldset>
            <p className="screen-note">{formatNote(shownStyle, columns)}</p>
          </section>
        )}

        <section className="build-fact" aria-labelledby="length-title">
          <h3 id="length-title">Length</h3>
          <fieldset className="page-choices">
            <legend>Fit the CV into</legend>
            {pageChoices(shownStyle).map((choice) => (
              <label key={choice.label} className="page-choice">
                <input
                  type="radio"
                  name="max-pages"
                  checked={maxPages === choice.value}
                  onChange={() => setMaxPages(choice.value)}
                />
                {choice.label}
              </label>
            ))}
          </fieldset>
          <p className="screen-note" aria-live="polite">
            {lengthText(layout, maxPages)}
          </p>
          {maxPages !== null && (
            <p className="screen-note">
              The limit is exact for the PDF. The DOCX uses the same text size and margins, but Word
              may break pages differently.
            </p>
          )}
        </section>

        <div className="downloads">
          <a
            className="btn btn-primary"
            href={cvDownloadUrl(analysis.analysis_id, 'docx', maxPages, style)}
            download
          >
            Download DOCX
          </a>
          <a
            className="btn btn-primary"
            href={cvDownloadUrl(analysis.analysis_id, 'pdf', maxPages, style)}
            download
          >
            Download PDF
          </a>
          <button type="button" className="btn btn-secondary" onClick={onStartOver}>
            Start over
          </button>
          <button type="button" className="btn btn-quiet" onClick={onDelete}>
            Delete my data
          </button>
        </div>
      </section>

      <section className="card" aria-labelledby="changes-title">
        <h3 id="changes-title">What changed</h3>
        <p className="screen-note">{countChanges(report.diff)}</p>
        <LineDiff lines={report.diff} titles={titles} />
      </section>

      <HowComputed usage={analysis.usage} />
    </div>
  )
}

function orderNote(builtBy: BuildReport['built_by']): string {
  return builtBy === 'agent'
    ? 'You asked for a new order, so an AI agent moved sections and entries for this job. It cannot change words: the only text changes are the suggestions you accepted.'
    : 'Your CV keeps its own order. The only text changes are the suggestions you accepted.'
}

function countChanges(diff: DiffLine[]): string {
  const count = (status: DiffLine['status']) => diff.filter((line) => line.status === status).length
  return [
    `${count('changed')} changed`,
    `${count('added')} added`,
    `${count('removed')} removed`,
    `${count('unchanged')} unchanged`,
  ].join(', ')
}

// The length of the built CV for a page limit, asked again when the limit changes. A reply for
// an outdated limit is dropped.
function useCvLayout(
  analysisId: string,
  maxPages: number | null,
  style: CvStyle | null,
): LayoutState {
  const key = `${maxPages ?? 'any'}:${style ?? 'auto'}`
  const [answer, setAnswer] = useState<{ key: string; state: LayoutState } | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getCvLayout(analysisId, maxPages, style, controller.signal)
      .then((layout) => {
        if (!controller.signal.aborted) {
          setAnswer({ key, state: { status: 'ready', layout } })
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setAnswer({ key, state: { status: 'failed' } })
      })
    return () => controller.abort()
  }, [analysisId, maxPages, style, key])

  return answer !== null && answer.key === key ? answer.state : { status: 'loading' }
}

function pagesText(count: number): string {
  return `${count} ${count === 1 ? 'page' : 'pages'}`
}

function lengthText(state: LayoutState, maxPages: number | null): string {
  if (state.status === 'loading') return 'Measuring the length...'
  if (state.status === 'failed') return 'The length could not be measured.'
  const { pages, fits, font_size: size, standard_font_size: standard, style } = state.layout
  const original = state.layout.original_pages
  const tightened = size === standard ? '' : ` The text is at ${size} pt instead of ${standard} pt so that it fits. Nothing is cut.`
  if (maxPages === null) {
    if (style !== 'original' || original === null) return `Your new CV takes ${pagesText(pages)}.`
    if (fits) return `Your new CV takes ${pagesText(pages)}, like the CV you uploaded.${tightened}`
    return `Your new CV takes ${pagesText(pages)}; the CV you uploaded takes ${pagesText(original)}. Nothing is cut, so accept fewer added lines or allow more pages.`
  }
  if (!fits) {
    return `It does not fit in ${pagesText(maxPages)}: with the smallest text that still reads well it takes ${pagesText(pages)}. Nothing is cut, so shorten your CV or allow more pages.`
  }
  if (size === standard) return `It fits in ${pagesText(maxPages)} as it is.`
  return `It fits in ${pagesText(maxPages)} with the text at ${size} pt instead of ${standard} pt. Nothing is cut.`
}

function formatNote(style: CvStyle | null, columns: number): string {
  if (style === 'standard') {
    return 'A plain template that screening software reads well. It does not keep the look of your CV.'
  }
  if (columns > 1) {
    return 'Your CV has columns. The new CV keeps its fonts, sizes, bold and order, but in one column, which screening software reads more reliably.'
  }
  return 'Same fonts, sizes, bold, alignment and order as the CV you uploaded. Only the changes you accepted are different.'
}
