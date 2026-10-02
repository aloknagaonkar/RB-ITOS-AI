from pathlib import Path

PATH = Path("frontend/src/historicalReplay.tsx")
text = PATH.read_text(encoding="utf-8")

helper_anchor = "const n=(value:any,digits=2)=>value==null?'—':Number(value).toFixed(digits)\n"
helper_code = """
const isoDate=(d:Date)=>[
  d.getFullYear(),
  String(d.getMonth()+1).padStart(2,'0'),
  String(d.getDate()).padStart(2,'0'),
].join('-')

function recentPresetDates(days=45){
  const rows:string[]=[]
  const d=new Date()
  d.setHours(12,0,0,0)
  for(let i=0;i<days;i++){
    const day=d.getDay()
    if(day!==0 && day!==6) rows.push(isoDate(d))
    d.setDate(d.getDate()-1)
  }
  return rows
}
"""

if "function recentPresetDates(" not in text:
    if helper_anchor not in text:
        raise SystemExit("Safe-stop: helper insertion point not found.")
    text = text.replace(helper_anchor, helper_anchor + helper_code, 1)

state_anchor = "  const [refreshKey,setRefreshKey]=useState(0)\n"
state_code = """  const presetDates=useMemo(()=>{
    const values=new Set<string>([
      ...sessions.map(s=>s.session_date),
      ...recentPresetDates(45),
    ])
    return [...values].sort().reverse()
  },[sessions])
"""

if "const presetDates=useMemo(" not in text:
    if state_anchor not in text:
        raise SystemExit("Safe-stop: state insertion point not found.")
    text = text.replace(state_anchor, state_anchor + state_code, 1)

old = """      <label>Date
        <input
          type="date"
          value={selected}
          list="historical-replay-session-dates"
          onChange={e=>setSelected(e.target.value)}
        />
        <datalist id="historical-replay-session-dates">
          {sessions.map(s=><option key={s.session_date} value={s.session_date}/>)}
        </datalist>
      </label>"""

new = """      <div className="hr-date-controls">
        <label>Quick date
          <select
            value={presetDates.includes(selected)?selected:''}
            onChange={e=>{if(e.target.value)setSelected(e.target.value)}}
          >
            <option value="">Select a date…</option>
            {presetDates.map(d=><option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label>Custom date
          <input
            type="date"
            value={selected}
            onChange={e=>setSelected(e.target.value)}
          />
        </label>
      </div>"""

if new in text:
    print("Predefined date selector already applied.")
elif old in text:
    PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("Applied predefined historical date selector.")
else:
    raise SystemExit("Safe-stop: current date control block not found; no file modified.")
