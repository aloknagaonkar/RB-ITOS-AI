export default function HilegaRsiTwoRouteWorkspace({ mode }: { mode: 'live' | 'historical' }) {
  return <iframe
    title="RSI Two Route — Confirmed Midpoint simulation audit"
    src={`/api/live-shadow/hilega-rsi-two-route/workspace?mode=${mode}`}
    style={{ width: '100%', minHeight: '1400px', border: 0, display: 'block' }}
  />
}
