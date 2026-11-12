// A LinkedIn job link on its own: the whole text is one linkedin.com address that names a job
// (".../jobs/view/<id>" or "currentJobId=<id>"). The server checks the link again.
const JOB_LINK =
  /^(?:https?:\/\/)?(?:[\w-]+\.)*linkedin\.com\/\S*(?:jobs\/view\/\S*\d{6,15}|currentJobId=\d{6,15})\S*$/i

export function isLinkedInJobLink(text: string): boolean {
  return JOB_LINK.test(text.trim())
}
