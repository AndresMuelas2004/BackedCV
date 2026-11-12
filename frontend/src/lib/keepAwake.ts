// The public demo runs on a free server that goes to sleep after 15 minutes without requests and
// then needs close to a minute to wake up. While this page is open and visible, a small request
// every few minutes keeps the server awake, so the next click is answered at once. Coming back
// to the page after a while asks at once, so a server that fell asleep starts waking up early.
const PING_EVERY_MS = 9 * 60 * 1000

export function keepServerAwake(): () => void {
  const ping = () => {
    if (document.visibilityState !== 'visible') return
    void fetch('/api/health', { cache: 'no-store' }).catch(() => undefined)
  }
  const timer = window.setInterval(ping, PING_EVERY_MS)
  document.addEventListener('visibilitychange', ping)
  return () => {
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', ping)
  }
}
