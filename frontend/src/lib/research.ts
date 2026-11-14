import type { PersonGroup, ProgressEvent, ResearchPerson, ResearchStep } from '../api/types'

// The steps of the deeper analysis, in the order they are shown while it runs.
export const RESEARCH_STEPS: readonly { key: string; label: string }[] = [
  { key: 'plan', label: 'Reading the posting' },
  { key: 'search:company', label: 'Looking up the company' },
  { key: 'search:team', label: 'Looking for the hiring team' },
  { key: 'search:recruiting', label: 'Looking for recruiters and ways to apply' },
  { key: 'extract', label: 'Checking every name against its page' },
  { key: 'drafts', label: 'Writing your plan and messages' },
]

export const GROUP_ORDER: readonly PersonGroup[] = [
  'posting_owner',
  'hiring_team',
  'recruiting',
  'leadership',
  'peer',
]

export const GROUP_LABELS: Record<PersonGroup, string> = {
  posting_owner: 'Who owns this posting',
  hiring_team: 'The team you would join',
  recruiting: 'Recruiters and HR',
  leadership: 'Leadership',
  peer: 'People in a similar role',
}

// The key of the step a progress event is about: the three searches share one step name.
export function stepKey(progress: ProgressEvent<ResearchStep>): string {
  return progress.step === 'search' ? `search:${progress.topic ?? ''}` : progress.step
}

// Addresses come from web pages: only http(s) links are ever rendered as links.
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null
  return /^https?:\/\//i.test(url.trim()) ? url.trim() : null
}

export function isEmail(value: string): boolean {
  return /^[\w.+-]+@[\w-]+(\.[\w-]+)+$/.test(value.trim())
}

// The people of each group, in GROUP_ORDER; groups without people are left out.
export function groupPeople(people: ResearchPerson[]): { group: PersonGroup; people: ResearchPerson[] }[] {
  return GROUP_ORDER.map((group) => ({
    group,
    people: people.filter((person) => person.group === group),
  })).filter((entry) => entry.people.length > 0)
}
