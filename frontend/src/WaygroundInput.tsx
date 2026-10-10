import { useState } from 'react'
import { useStaffAction } from './StaffAction'

export type Report = { id: number; filename: string; sha256: string; metadata: { question_count: number }; participants: { source_row: number; player_name: string; score: string; answer_time_ms: number; counts: Record<string,number> }[] }
type Props = { roundId: number; reports: Report[]; teams: { code: string; name: string }[]; reason: string; action: ReturnType<typeof useStaffAction>; preview: (data: Record<string,unknown>) => void }

function fileBase64(file: File) {
  return new Promise<string>((resolve,reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(',')[1])
    reader.onerror = () => reject(new Error('Could not read the workbook.'))
    reader.readAsDataURL(file)
  })
}

export function WaygroundInput({ roundId,reports,teams,reason,action,preview }: Props) {
  const [file,setFile] = useState<File | null>(null)
  const [error,setError] = useState('')
  const latest = reports[0]
  return <><p>Upload the original Wayground export. Points come from Score; ties use lower Total Time Taken. Workbook values are retained privately. Map every player to a team or give an explicit exclusion reason.</p>
    <form className="form-stack" onSubmit={async event => { event.preventDefault(); setError(''); try { if (!file || !file.name.toLowerCase().endsWith('.xlsx') || file.size>1000000) throw new Error('Choose an original .xlsx export of at most 1 MB.'); const content_base64 = await fileBase64(file); action.send(`/api/staff/rounds/${roundId}/imports/wayground`,{ filename:file.name,content_base64,reason }) } catch (value) { setError(value instanceof Error ? value.message : 'Workbook unavailable.') } }}>
      <label>Wayground Excel export<input type="file" accept=".xlsx" required onChange={event => setFile(event.target.files?.[0] ?? null)} /></label><button disabled={!reason.trim() || !file}>Read Wayground workbook</button>
    </form>{error && <p role="alert">{error}</p>}
    {latest && <><p><a href={`/api/staff/rounds/${roundId}/imports/wayground/${latest.id}`} download>Download original private workbook</a></p><Mapping key={latest.id} report={latest} teams={teams} reason={reason} preview={preview} /></>}
  </>
}

function Mapping({ report,teams,reason,preview }: { report: Report; teams: Props['teams']; reason: string; preview: Props['preview'] }) {
  const initial = Object.fromEntries(report.participants.map(player => {
    const matches = teams.filter(team => [team.code,team.name].some(value => value.toLowerCase()===player.player_name.toLowerCase()))
    return [player.source_row,{ team:matches.length===1 ? matches[0].code : '',reason:'' }]
  }))
  const [mapped,setMapped] = useState<Record<number,{ team:string;reason:string }>>(initial)
  return <section><h3>Match exported players to teams</h3><p>{report.filename} · {report.metadata.question_count} questions</p><p>File checksum: <code>{report.sha256}</code></p><form className="form-stack" onSubmit={event => { event.preventDefault(); preview({ rows:report.participants.map(player => ({ report_id:report.id,source_row:player.source_row,team_code:mapped[player.source_row].team==='__EXCLUDE__' ? '' : mapped[player.source_row].team,excluded:mapped[player.source_row].team==='__EXCLUDE__',exclusion_reason:mapped[player.source_row].reason })) }) }}>
    {report.participants.map(player => <fieldset key={player.source_row}><legend>{player.player_name}</legend><p>{player.score} platform points · {(player.answer_time_ms/1000).toFixed(3)} seconds reported answering duration · {player.counts.Correct} correct</p>
      <label>Team for {player.player_name}<select required value={mapped[player.source_row].team} onChange={event => setMapped(old => ({ ...old,[player.source_row]:{ team:event.target.value,reason:'' } }))}><option value="">Choose a qualified team</option>{teams.map(team => <option key={team.code} value={team.code}>{team.code} · {team.name}</option>)}<option value="__EXCLUDE__">Exclude from this competition import</option></select></label>
      {mapped[player.source_row].team==='__EXCLUDE__' && <label>Exclusion reason for {player.player_name}<input required maxLength={200} value={mapped[player.source_row].reason} onChange={event => setMapped(old => ({ ...old,[player.source_row]:{ ...old[player.source_row],reason:event.target.value } }))} /></label>}
    </fieldset>)}<button disabled={!reason.trim()}>Dry-run Wayground scores</button>
  </form></section>
}
