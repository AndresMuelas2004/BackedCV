import { useState, type FormEvent } from 'react'
import { describeError } from '../../lib/errors'
import { TIER_LABELS, TIERS, type PriorityItem } from '../../lib/priorities'

interface FixListProps {
  items: PriorityItem[]
  busy: boolean // true while a request of the report is in flight
  // Saves what the candidate says about a requirement; null removes it.
  onTell: (requirementId: string, text: string | null) => Promise<void>
}

// How many items show before "Show more". Everything that could rule the candidate out always shows.
const FIRST_ITEMS = 5

export default function FixList({ items, busy, onTell }: FixListProps) {
  const [toggled, setToggled] = useState<Record<string, boolean>>({})
  const [showAll, setShowAll] = useState(false)

  const ruleOut = items.filter((item) => item.tier === 'rule_out').length
  const limit = Math.max(FIRST_ITEMS, ruleOut)
  const visible = showAll ? items : items.slice(0, limit)
  const extra = items.length - limit

  return (
    <section className="rp-fix" aria-labelledby="fix-title">
      <div className="rp-fix-head">
        <div>
          <h2 id="fix-title" className="rp-h2">
            What to fix, most important first
          </h2>
          <p className="rp-muted">
            {items.length === 0
              ? 'Nothing to fix. Your CV backs what this posting asks.'
              : `${items.length} ${items.length === 1 ? 'thing' : 'things'}. Start at the top.`}
          </p>
        </div>
        {items.length > 0 && (
          <ul className="rp-legend" aria-label="What the colors mean">
            {TIERS.map((tier) => (
              <li key={tier} className={`rp-legend-item tier-${tier}`}>
                <span className="rp-legend-dot" aria-hidden="true" />
                {TIER_LABELS[tier]}
              </li>
            ))}
          </ul>
        )}
      </div>

      {items.length > 0 && (
        <ol className="rp-fix-list">
          {visible.map((item, index) => {
            const open = toggled[item.key] ?? index === 0
            return (
              <li key={item.key}>
                <FixItem
                  item={item}
                  number={index + 1}
                  open={open}
                  onToggle={() => setToggled((previous) => ({ ...previous, [item.key]: !open }))}
                  busy={busy}
                  onTell={onTell}
                />
              </li>
            )
          })}
        </ol>
      )}

      {/* The button stays after expanding, so the keyboard focus is never dropped. */}
      {extra > 0 && (
        <button
          type="button"
          className="rp-btn rp-btn-secondary rp-more"
          aria-expanded={showAll}
          onClick={() => setShowAll((previous) => !previous)}
        >
          {showAll ? 'Show fewer' : `Show ${extra} more`}
        </button>
      )}
    </section>
  )
}

interface FixItemProps {
  item: PriorityItem
  number: number
  open: boolean
  onToggle: () => void
  busy: boolean
  onTell: (requirementId: string, text: string | null) => Promise<void>
}

function FixItem({ item, number, open, onToggle, busy, onTell }: FixItemProps) {
  const panelId = `fix-${item.key}-panel`
  const titleId = `fix-${item.key}-title`
  const hasDetail = item.jobQuote !== null || item.cvQuote !== null || item.action !== '' || item.canTell
  return (
    <article className={`rp-item tier-${item.tier}`} aria-labelledby={titleId}>
      <div className="rp-item-head">
        <span className="rp-item-number" aria-hidden="true">
          {number}
        </span>
        <div className="rp-item-body">
          <p className="rp-item-tags">
            <span className="rp-pill">{TIER_LABELS[item.tier]}</span>
            <span className="rp-item-tag">{item.tag}</span>
          </p>
          <h3 id={titleId} className="rp-item-title">
            <span className="visually-hidden">{number}. </span>
            {item.title}
          </h3>
          <p className="rp-item-why">{item.why}</p>
        </div>
        {hasDetail && (
          <button
            type="button"
            className="rp-btn rp-btn-secondary rp-toggle"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={onToggle}
          >
            {open ? 'Hide' : 'See why'}
          </button>
        )}
      </div>

      {hasDetail && (
        <div className="rp-item-detail" id={panelId} hidden={!open}>
          <div className="rp-sides">
            <div className="rp-side">
              <p className="rp-side-label">The job says</p>
              <p className="rp-side-text">
                {item.jobQuote ? `"${item.jobQuote}"` : 'No exact sentence for this in the posting.'}
              </p>
            </div>
            <div className="rp-side">
              <p className="rp-side-label">
                Your CV says{item.cvQuote && item.cvSource ? ` · ${item.cvSource}` : ''}
              </p>
              <p className={item.cvQuote ? 'rp-side-text' : 'rp-side-text is-empty'}>
                {item.cvQuote ? `"${item.cvQuote}"` : 'Nothing in your CV mentions it.'}
              </p>
            </div>
          </div>
          {item.action !== '' && (
            <p className="rp-todo">
              <strong>What to do:</strong> <span>{item.action}</span>
            </p>
          )}
          {item.canTell && item.requirementId !== null && (
            <TellUs
              key={item.statement ?? ''}
              id={`fix-${item.key}-tell`}
              saved={item.statement}
              busy={busy}
              onSave={(text) => onTell(item.requirementId as string, text)}
            />
          )}
        </div>
      )}
    </article>
  )
}

interface TellUsProps {
  id: string
  saved: string | null // what the candidate already told us
  busy: boolean
  onSave: (text: string | null) => Promise<void>
}

const STATEMENT_MAX = 500 // the server's limit (domain/models/assessment.py)

// The candidate says, in their own words, where and how they did what the CV leaves out. Only
// these words can become a new CV line, and that line is checked against them.
function TellUs({ id, saved, busy, onSave }: TellUsProps) {
  const [text, setText] = useState(saved ?? '')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  async function send(next: string | null) {
    if (pending || busy) return
    setPending(true)
    setError(null)
    try {
      await onSave(next)
    } catch (failure) {
      setError(describeError(failure))
    } finally {
      setPending(false)
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next = text.trim()
    if (next === '') {
      setError('Write where and how you did it first.')
      return
    }
    void send(next)
  }

  return (
    <form className="rp-tell" onSubmit={submit} noValidate>
      <label htmlFor={id} className="rp-tell-label">
        {saved ? 'You told us' : 'Have you done this? Say where and how, in your own words.'}
      </label>
      <textarea
        id={id}
        rows={2}
        maxLength={STATEMENT_MAX}
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="For example: At Acme I ran our API on Kubernetes for two years."
        aria-invalid={error !== null}
        aria-describedby={`${id}-hint`}
      />
      <p id={`${id}-hint`} className="rp-tell-hint">
        Only what you write here can become a new line of your CV, and the line is checked against
        your words. Leave it empty if you have not done it.
      </p>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="rp-tell-actions">
        {/* aria-disabled, not disabled: a disabled button drops the keyboard focus it has. */}
        <button type="submit" className="rp-btn rp-btn-secondary" aria-disabled={busy || pending}>
          {pending ? 'Saving...' : saved ? 'Update' : 'Add it to my new CV'}
        </button>
        {saved && (
          <button
            type="button"
            className="rp-btn rp-btn-secondary"
            aria-disabled={busy || pending}
            onClick={() => void send(null)}
          >
            Remove
          </button>
        )}
      </div>
    </form>
  )
}
