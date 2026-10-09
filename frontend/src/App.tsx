import { useQuery } from '@tanstack/react-query'
import { getJson } from './api'
import { Login, Lobby } from './Participant'
import { StaffRounds } from './StaffRounds'
import { Mission } from './Mission'
import { PublishedResults, StaffResults } from './Results'
import { CodingWorkspace } from './CodingWorkspace'
import { StaffCoding } from './StaffCoding'
import { StaffScores } from './StaffScores'
import { StaffRoster } from './StaffRoster'
import { StaffBuzzer } from './StaffBuzzer'

const rounds = [
  ['01', 'Treasure hunt', 'Follow the clues. Find your next move.'],
  ['02', 'Quiz & puzzles', 'Connect your discoveries.'],
  ['03', 'Coding & debugging', 'Turn a problem into a solution.'],
  ['04', 'Faculty challenge', 'Put your thinking to the test.'],
  ['05', 'The buzzer final', 'Buzz online. Answer at the venue.'],
] as const

export function App() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: ({ signal }) => getJson<{ status: string }>('/api/health', signal),
    staleTime: 30_000,
  })
  const connection = health.isError
    ? 'Connection unavailable'
    : health.isPending
      ? 'Checking connection'
      : 'Connected'

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="site-header">
        <a className="wordmark" href="/" aria-label="Tech Treasure Hunt home">
          <span className="brand-icon" aria-hidden="true">↗</span>
          <span>AI NEXUS <span className="brand-secondary">/ TECH-PRAVAH 26</span></span>
        </a>
        <span className="connection" role="status">
          <span className={`connection-dot ${health.isError ? 'offline' : ''}`} aria-hidden="true" />
          {connection}
        </span>
      </header>

      <main id="main">
        {location.pathname === '/staff/buzzer' ? <StaffBuzzer /> : <>
        {location.pathname === '/staff/scores' ? <StaffScores /> : location.pathname === '/staff/roster' ? <StaffRoster /> : location.pathname === '/staff/coding' ? <StaffCoding /> : /^\/rounds\/[1-9][0-9]*\/coding$/.test(location.pathname) ? <CodingWorkspace /> : location.pathname === '/staff/results' ? <StaffResults /> : /^\/rounds\/[1-9][0-9]*\/results$/.test(location.pathname) ? <PublishedResults /> : /^\/rounds\/[1-9][0-9]*$/.test(location.pathname) ? <Lobby roundId={Number(location.pathname.split('/')[2])} /> : location.pathname === '/staff/rounds' ? <StaffRounds /> : location.pathname === '/login' ? <Login /> : location.pathname.startsWith('/missions/') ? <Mission /> : location.pathname === '/lobby' ? <Lobby /> : <>
        <section className="hero" aria-labelledby="hero-heading">
          <div className="hero-copy">
            <p className="eyebrow">12–13 OCTOBER 2026 · SKIT JAIPUR</p>
            <h1 id="hero-heading">Think fast.<br />Look closer.<br /><span>Find the treasure.</span></h1>
            <p className="hero-description">A campus full of clues. A team full of ideas. Five rounds to connect the dots and see how far your curiosity takes you.</p>
            <div className="access-note">
              <span className="note-icon" aria-hidden="true">↗</span>
              <div><a href="/login"><strong>Team sign in →</strong></a><p>Have your credentials ready. Your next move starts here.</p></div>
            </div>
          </div>
          <div className="hunt-map" aria-hidden="true">
            <div className="map-grid" />
            <svg className="map-route" viewBox="0 0 440 420" fill="none">
              <path d="M80 315 L80 205 L208 205 L208 88 L355 88 L355 315 L270 315" stroke="currentColor" strokeWidth="2" strokeDasharray="7 7" />
              <circle cx="80" cy="315" r="7" fill="currentColor" />
              <circle cx="208" cy="205" r="7" fill="currentColor" />
              <circle cx="355" cy="88" r="7" fill="currentColor" />
            </svg>
            <span className="map-label label-start">START HERE</span>
            <span className="map-clue">{'{ clue_01 }'}</span>
            <span className="map-marker">?</span>
            <div className="treasure"><span>✦</span><small>THE NEXT DISCOVERY</small></div>
            <span className="map-coordinate">26.91° N / 75.78° E</span>
            <span className="map-caption">EVERY CLUE IS A NEW DIRECTION.</span>
          </div>
        </section>

        <section className="round-section" aria-labelledby="rounds-heading">
          <div className="section-heading"><p className="eyebrow">THE PATH AHEAD</p><h2 id="rounds-heading">One team. Five challenges.</h2></div>
          <ol className="round-list">
            {rounds.map(([number, title, description]) => (
              <li key={number}><span className="round-number">{number}</span><h3>{title}</h3><p>{description}</p></li>
            ))}
          </ol>
        </section>
        </>}
        </>}
      </main>

      <footer><span>TECH TREASURE HUNT</span><span>AI Nexus Club · CSE Department · SKIT Jaipur</span></footer>
    </div>
  )
}
