import { useEffect, useRef, useState } from 'react'
import { ApiError, getResearch, runResearch } from '../../api/client'
import type {
  AnalysisReport,
  ChannelKind,
  ErrorBody,
  OutreachDraft,
  ResearchChannel,
  ResearchReport,
  ResearchView,
} from '../../api/types'
import { GROUP_LABELS, RESEARCH_STEPS, groupPeople, isEmail, safeHref, stepKey } from '../../lib/research'
import './DeepAnalysis.css'

type State =
  | { status: 'checking' }
  | { status: 'unavailable' }
  | { status: 'idle' }
  | { status: 'running'; done: string[] } // keys of the steps that finished
  | { status: 'done'; report: ResearchReport }
  | { status: 'failed'; error: ErrorBody }

const RESEARCH_FAILED: ErrorBody = {
  code: 'research_failed',
  title: 'The deeper analysis could not finish.',
  detail: '',
}

const CHANNEL_LABELS: Record<ChannelKind, string> = {
  email: 'Email',
  application: 'Apply',
  careers_page: 'Careers page',
  company_profile: 'Company profile',
  other: 'Other',
}

// Polling is slow on purpose: a run takes about a minute.
const POLL_MS = 3000

function fromView(view: ResearchView): State {
  if (!view.available) return { status: 'unavailable' }
  if (view.status === 'done' && view.report) return { status: 'done', report: view.report }
  if (view.status === 'running') return { status: 'running', done: [] }
  if (view.status === 'failed') return { status: 'failed', error: view.error ?? RESEARCH_FAILED }
  return { status: 'idle' }
}

function errorOf(error: unknown): ErrorBody {
  if (error instanceof ApiError) {
    return { code: error.code, title: error.title, detail: error.detail }
  }
  return RESEARCH_FAILED
}

export default function DeepAnalysis({ analysis }: { analysis: AnalysisReport }) {
  const [state, setState] = useState<State>({ status: 'checking' })
  // True while this component holds the run's stream; polling then stays quiet.
  const streaming = useRef(false)
  const running = state.status === 'running'
  const hasCompany = Boolean(analysis.job?.company?.trim())

  // Reads what the server already has for this analysis: a finished report, a run in progress.
  useEffect(() => {
    const controller = new AbortController()
    getResearch(analysis.analysis_id, controller.signal)
      .then((view) => setState(fromView(view)))
      .catch(() => {
        if (!controller.signal.aborted) setState({ status: 'idle' })
      })
    return () => controller.abort()
  }, [analysis.analysis_id])

  // A run started elsewhere (another tab, a reload) is followed until the server says it is over.
  useEffect(() => {
    if (!running) return
    const id = analysis.analysis_id
    const controller = new AbortController()
    const timer = window.setInterval(() => {
      if (streaming.current) return
      getResearch(id, controller.signal)
        .then((view) => {
          if (view.status !== 'running') setState(fromView(view))
        })
        .catch(() => {
          // A failed poll is tried again on the next tick.
        })
    }, POLL_MS)
    return () => {
      window.clearInterval(timer)
      controller.abort()
    }
  }, [running, analysis.analysis_id])

  async function run() {
    streaming.current = true
    setState({ status: 'running', done: [] })
    try {
      await runResearch(analysis.analysis_id, (event) => {
        if (event.type === 'progress') {
          if (event.progress.status !== 'done') return
          const key = stepKey(event.progress)
          setState((current) =>
            current.status === 'running' && !current.done.includes(key)
              ? { status: 'running', done: [...current.done, key] }
              : current,
          )
        } else if (event.type === 'research') {
          setState(fromView(event.view))
        } else {
          setState({ status: 'failed', error: event.error })
        }
      })
    } catch (error) {
      setState({ status: 'failed', error: errorOf(error) })
    } finally {
      streaming.current = false
    }
  }

  if (state.status === 'checking' || state.status === 'unavailable') return null

  return (
    <section className="rp-card rs" aria-labelledby="rs-title">
      <h2 id="rs-title" className="rp-h2-sm">
        Deeper analysis of this job
      </h2>

      {state.status === 'idle' && (
        <>
          <p className="rs-lead">
            When a job really matters to you, look past the posting: what the company does, who is
            hiring, who recruits for it and how to reach them, with messages ready to send.
          </p>
          <p className="screen-note">
            It searches public web pages and takes about a minute. A name or an address is shown only
            when a page backs it.
          </p>
          {!hasCompany && (
            <p className="notice notice-info">
              The posting does not name the company, so there is nothing to look up.
            </p>
          )}
          <div>
            <button type="button" className="btn btn-primary" onClick={run} disabled={!hasCompany}>
              Run the deeper analysis
            </button>
          </div>
        </>
      )}

      {state.status === 'running' && (
        <>
          <p className="screen-note" role="status">
            Searching public pages. This takes about a minute; you can keep reading your report.
          </p>
          <ul className="rs-steps">
            {RESEARCH_STEPS.map((step) => {
              const finished = state.done.includes(step.key)
              return (
                <li key={step.key} className={finished ? 'rs-step-done' : undefined}>
                  <span aria-hidden="true">{finished ? '✓' : '…'}</span>
                  {step.label}
                </li>
              )
            })}
          </ul>
        </>
      )}

      {state.status === 'failed' && (
        <>
          <div className="notice notice-warn" role="alert">
            <p>{state.error.title}</p>
            {state.error.detail && <p>{state.error.detail}</p>}
          </div>
          <div>
            <button type="button" className="btn btn-primary" onClick={run}>
              Try again
            </button>
          </div>
        </>
      )}

      {state.status === 'done' && <DoneReport report={state.report} onRunAgain={run} />}
    </section>
  )
}

function DoneReport({ report, onRunAgain }: { report: ResearchReport; onRunAgain: () => void }) {
  const { company } = report
  return (
    <>
      <p className="screen-note">
        From {report.searches} web searches. Pages can be out of date: open a profile before you write
        to someone.
      </p>

      {(company.summary || company.facts.length > 0) && (
        <div className="rs-block">
          <h3>{company.name ? `The company: ${company.name}` : 'The company'}</h3>
          {company.summary && <p>{company.summary}</p>}
          {company.facts.length > 0 && (
            <dl className="rs-facts">
              {company.facts.map((fact, index) => (
                <div key={`${fact.label}-${index}`}>
                  <dt>{fact.label}</dt>
                  <dd>
                    {fact.value} <SourceLink url={fact.source_url} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      )}

      <div className="rs-block">
        <h3>People to reach</h3>
        {report.people.length === 0 && (
          <p className="screen-note">No person could be confirmed from public pages.</p>
        )}
        {groupPeople(report.people).map(({ group, people }) => (
          <div className="rs-group" key={group}>
            <h4>{GROUP_LABELS[group]}</h4>
            <ul className="rs-people">
              {people.map((person) => {
                const profile = safeHref(person.profile_url)
                return (
                  <li className="rs-person" key={person.id}>
                    <p className="rs-person-name">
                      <strong>{person.name}</strong> <span>{person.role}</span>
                    </p>
                    <p>{person.why}</p>
                    <p className="rs-links">
                      {profile !== null && (
                        <a href={profile} target="_blank" rel="noreferrer noopener">
                          Profile
                        </a>
                      )}
                      <SourceLink url={person.source_url} />
                    </p>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </div>

      {report.channels.length > 0 && (
        <div className="rs-block">
          <h3>Ways to reach the company</h3>
          <ul className="rs-channels">
            {report.channels.map((channel) => (
              <li key={channel.id}>
                <span className="rs-channel-kind">{CHANNEL_LABELS[channel.kind]}</span>
                <ChannelValue channel={channel} />
                <span className="rs-origin">
                  {channel.source_url ? <SourceLink url={channel.source_url} /> : 'From the posting'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.actions.length > 0 && (
        <div className="rs-block">
          <h3>Your plan</h3>
          <ol className="rs-actions">
            {report.actions.map((action) => (
              <li className="rs-action" key={action.id}>
                <p className="rs-action-title">
                  <strong>{action.title}</strong>
                </p>
                <p>{action.why}</p>
                {action.draft && <DraftBox draft={action.draft} />}
              </li>
            ))}
          </ol>
          <p className="screen-note">
            The messages only use what your CV says. Read them and make them yours before you send them.
          </p>
        </div>
      )}

      {report.notes.length > 0 && (
        <div className="rs-block">
          <h3>What could not be found</h3>
          <ul className="rs-notes">
            {report.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      {report.sources.length > 0 && (
        <details className="rp-fold">
          <summary>
            <span>Pages the searches returned ({report.sources.length})</span>
            <span className="rp-fold-hint">Show</span>
          </summary>
          <div className="rp-fold-body">
            <ul className="rs-sources">
              {report.sources.map((source, index) => {
                const href = safeHref(source.url)
                return (
                  <li key={`${source.url}-${index}`}>
                    {href !== null ? (
                      <a href={href} target="_blank" rel="noreferrer noopener">
                        {source.title || source.url}
                      </a>
                    ) : (
                      source.title || source.url
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        </details>
      )}

      <div>
        <button type="button" className="btn btn-secondary" onClick={onRunAgain}>
          Run it again
        </button>
      </div>
    </>
  )
}

// A link to the page a fact came from. Nothing is shown when the address is not web.
function SourceLink({ url }: { url: string | null | undefined }) {
  const href = safeHref(url)
  if (href === null) return null
  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      Source
    </a>
  )
}

function ChannelValue({ channel }: { channel: ResearchChannel }) {
  if (channel.kind === 'email' && isEmail(channel.value)) {
    return (
      <>
        <a href={`mailto:${channel.value.trim()}`}>{channel.value}</a>
        <span>{channel.label}</span>
      </>
    )
  }
  const href = safeHref(channel.value)
  if (href !== null) {
    return (
      <a href={href} target="_blank" rel="noreferrer noopener">
        {channel.label}
      </a>
    )
  }
  return <span>{channel.value}</span>
}

function DraftBox({ draft }: { draft: OutreachDraft }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    const text = draft.subject ? `${draft.subject}\n\n${draft.body}` : draft.body
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
    } catch {
      // The clipboard can refuse; the text stays on screen to copy by hand.
    }
  }

  return (
    <div className="rs-draft">
      {draft.subject && <p className="rs-draft-subject">Subject: {draft.subject}</p>}
      <pre className="rs-draft-body">{draft.body}</pre>
      <div className="rs-draft-foot">
        <span>{draft.body.length} characters</span>
        <button type="button" className="btn btn-quiet" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  )
}
