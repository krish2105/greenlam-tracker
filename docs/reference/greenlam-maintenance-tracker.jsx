import { useState, useEffect } from 'react';
import * as XLSX from 'xlsx';
import { Flag, Bell, Search, Package, Wrench, Check, ShieldCheck, Clock, AlertTriangle, Star, Plus, BarChart3, ClipboardList, ChevronLeft, RotateCcw, Loader2, Layers, Lock, Download } from 'lucide-react';

// Change this to whatever code plant leadership should use to open the Dashboard tab.
// This is a soft gate only (no real login system) - anyone who can read the code can find it.
const DASHBOARD_PASSCODE = 'PLANTHEAD';

// A machine gets flagged for preventive maintenance once it has this many breakdowns logged.
const PM_THRESHOLD = 3;

const C = {
  ink: '#22251F',
  paper: '#F7F6F2',
  paperMuted: '#EDEBE2',
  line: '#E1DED3',
  primary: '#1F5F3F',
  primaryTint: '#E7EEE8',
  amber: '#A8672A',
  amberTint: '#F4EAD9',
  rust: '#9A3E2E',
  rustTint: '#F5E3DF',
  muted: '#8B8A7F',
};

const STAGES = [
  { key: 'raised', label: 'Raised', icon: Flag },
  { key: 'ack', label: 'Acknowledged', icon: Bell },
  { key: 'material', label: 'Material check', icon: Package },
  { key: 'repair', label: 'Repair in progress', icon: Wrench },
  { key: 'resolved', label: 'Resolved', icon: Check },
  { key: 'diagnosis', label: 'Root cause found', icon: Search },
  { key: 'closed', label: 'Verified & closed', icon: ShieldCheck },
];

const STATUS_LABELS = ['Raised', 'Acknowledged', 'Sourcing material', 'Repair in progress', 'Resolved', 'Diagnosing', 'Closed'];
const SECTIONS = ['Press', 'Impregnation', 'Sanding', 'Cutting', 'Resin', 'Paper', 'Boiler/Utility', 'Other'];
const CATEGORIES = ['Mechanical', 'Electrical', 'Boiler', 'Process', 'Temp.', 'Other'];
const PRIORITIES = ['Low', 'Medium', 'High', 'Critical'];
const TEXTURES = ['Glossy', 'Suede/Matte', 'Textured', 'Metallic', 'Other'];
const REJECT_REASONS = ['Surface defect', 'Dimension variation', 'Thickness variation', 'Color/shade mismatch', 'Delamination', 'Edge damage', 'Other'];
const MACHINE_SUGGESTIONS = {
  'Press': ['Press-1', 'Press-2', 'Press-3', 'Press-4', 'Press-5'],
  'Impregnation': ['IMP-1', 'IMP-2', 'IMP-3', 'IMP-4', 'IMP-5', 'IMP-6', 'IMP-7', 'IMP-8', 'IMP-9', 'IMP-10', 'IMP-11', 'IMP-12'],
  'Sanding': ['Sanding-1', 'Sanding-2', 'Sanding-3', 'Sanding-4'],
  'Cutting': ['DD Saw-1', 'DD Saw-2', 'Shearing-1', 'Shearing-2'],
  'Resin': ['Resin Kettle-1', 'Resin Kettle-2', 'Resin Kettle-3'],
  'Paper': ['Paper Crane'],
  'Boiler/Utility': ['Boiler-1', 'DG Set-1', 'DG Set-2', 'Cooling Tower'],
  'Other': [],
};

function uid() {
  return 'MT-' + Math.random().toString(36).slice(2, 7).toUpperCase();
}
function nowIso() {
  return new Date().toISOString();
}
function fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ', ' +
    d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}
function monthLabel(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString('en-US', { month: 'short' }) + '-' + d.getFullYear();
}
function fmtMinutes(mins) {
  const m = Math.round(mins);
  if (m < 1) return '<1 min';
  if (m < 60) return m + ' min';
  const h = Math.floor(m / 60);
  const remM = m % 60;
  if (h < 24) return h + 'h ' + remM + 'm';
  const d = Math.floor(h / 24);
  return d + 'd ' + (h % 24) + 'h';
}
function fmtDuration(startIso, endIso) {
  if (!startIso || !endIso) return '';
  const ms = new Date(endIso) - new Date(startIso);
  if (ms < 0) return '';
  return fmtMinutes(ms / 60000);
}
function bdMinutesOf(t) {
  if (!t.timestamps.raised || !t.timestamps.resolved) return null;
  return (new Date(t.timestamps.resolved) - new Date(t.timestamps.raised)) / 60000;
}
function getRecurrence(ticket, allTickets) {
  const matches = allTickets.filter(t =>
    t.id !== ticket.id &&
    t.asset.trim().toLowerCase() === ticket.asset.trim().toLowerCase() &&
    t.category === ticket.category
  );
  return { count: matches.length + 1, previous: matches.map(t => fmtDateTime(t.timestamps.raised)) };
}
function computeInsights(tickets) {
  const open = tickets.filter(t => t.currentStage < 6).length;
  const withResponse = tickets.filter(t => t.timestamps.raised && t.timestamps.ack);
  const avgResponseMins = withResponse.length
    ? withResponse.reduce((sum, t) => sum + (new Date(t.timestamps.ack) - new Date(t.timestamps.raised)) / 60000, 0) / withResponse.length
    : null;
  const now = new Date();
  const resolvedThisMonth = tickets.filter(t => {
    if (!t.timestamps.resolved) return false;
    const d = new Date(t.timestamps.resolved);
    return d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
  }).length;
  const groups = {};
  tickets.forEach(t => {
    const key = t.asset.trim().toLowerCase() + '|' + t.category;
    groups[key] = groups[key] || { asset: t.asset, category: t.category, count: 0 };
    groups[key].count += 1;
  });
  const recurring = Object.values(groups).filter(g => g.count > 1).sort((a, b) => b.count - a.count);
  const catTimes = {};
  tickets.forEach(t => {
    if (t.timestamps.raised && t.timestamps.resolved) {
      const mins = (new Date(t.timestamps.resolved) - new Date(t.timestamps.raised)) / 60000;
      catTimes[t.category] = catTimes[t.category] || [];
      catTimes[t.category].push(mins);
    }
  });
  const avgByCategory = Object.keys(catTimes).map(cat => {
    const arr = catTimes[cat];
    return { category: cat, avgMins: arr.reduce((a, b) => a + b, 0) / arr.length };
  });
  return { open, avgResponseMins, resolvedThisMonth, recurring, avgByCategory };
}
function computeBdStats(tickets) {
  const withBd = tickets.map(t => ({ t, mins: bdMinutesOf(t) })).filter(x => x.mins != null);
  const totalMin = withBd.reduce((s, x) => s + x.mins, 0);
  const bySection = {};
  withBd.forEach(({ t, mins }) => {
    const sec = t.section || 'Unspecified';
    bySection[sec] = bySection[sec] || { section: sec, min: 0, count: 0 };
    bySection[sec].min += mins;
    bySection[sec].count += 1;
  });
  return {
    totalIssues: tickets.length,
    totalMin: Math.round(totalMin),
    totalHrs: +(totalMin / 60).toFixed(2),
    bySection: Object.values(bySection).sort((a, b) => b.min - a.min),
  };
}
function computePmCandidates(tickets) {
  const groups = {};
  tickets.forEach(t => {
    const key = t.asset.trim().toLowerCase();
    groups[key] = groups[key] || { asset: t.asset, section: t.section, count: 0, lastDate: null };
    groups[key].count += 1;
    if (!groups[key].lastDate || new Date(t.timestamps.raised) > new Date(groups[key].lastDate)) {
      groups[key].lastDate = t.timestamps.raised;
    }
  });
  return Object.values(groups).filter(g => g.count >= PM_THRESHOLD).sort((a, b) => b.count - a.count);
}
function computeProductionStats(production) {
  const totalProduced = production.reduce((s, p) => s + (Number(p.produced) || 0), 0);
  const totalRejected = production.reduce((s, p) => s + (Number(p.rejected) || 0), 0);
  const rejectRate = totalProduced > 0 ? (totalRejected / totalProduced) * 100 : 0;
  const byTexture = {};
  production.forEach(p => {
    byTexture[p.texture] = byTexture[p.texture] || { texture: p.texture, produced: 0, rejected: 0 };
    byTexture[p.texture].produced += Number(p.produced) || 0;
    byTexture[p.texture].rejected += Number(p.rejected) || 0;
  });
  const byReason = {};
  production.forEach(p => {
    if (Number(p.rejected) > 0 && p.rejectReason) {
      byReason[p.rejectReason] = (byReason[p.rejectReason] || 0) + Number(p.rejected);
    }
  });
  return {
    totalProduced,
    totalRejected,
    rejectRate: +rejectRate.toFixed(1),
    byTexture: Object.values(byTexture),
    byReason: Object.entries(byReason).map(([reason, count]) => ({ reason, count })).sort((a, b) => b.count - a.count),
  };
}

function TicketTag({ id }) {
  return (
    <span className="font-mono text-xs px-1.5 py-0.5 rounded border inline-block -rotate-1" style={{ borderColor: C.line, color: C.muted, backgroundColor: '#FFFFFF' }}>
      {id}
    </span>
  );
}
function Badge({ children, tone = 'neutral' }) {
  const map = {
    neutral: { bg: C.paperMuted, text: C.muted },
    blue: { bg: '#E7EEF3', text: '#2E5A78' },
    amber: { bg: C.amberTint, text: C.amber },
    green: { bg: C.primaryTint, text: C.primary },
    red: { bg: C.rustTint, text: C.rust },
  };
  const t = map[tone] || map.neutral;
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap" style={{ backgroundColor: t.bg, color: t.text }}>
      {children}
    </span>
  );
}
function Row({ label, value }) {
  return (
    <div className="flex justify-between gap-3 text-sm py-0.5">
      <span style={{ color: C.muted }}>{label}</span>
      <span className="text-right" style={{ color: C.ink }}>{value}</span>
    </div>
  );
}
function InfoCard({ label, children }) {
  return (
    <div className="rounded-lg p-3 mb-2" style={{ backgroundColor: C.paperMuted }}>
      <p className="text-xs mb-1.5" style={{ color: C.muted }}>{label}</p>
      {children}
    </div>
  );
}
function StatCard({ label, value }) {
  return (
    <div className="rounded-xl p-3 border" style={{ borderColor: C.line }}>
      <p className="text-xl font-semibold" style={{ color: C.primary }}>{value}</p>
      <p className="text-xs mt-0.5" style={{ color: C.muted }}>{label}</p>
    </div>
  );
}
function PrimaryButton({ children, onClick, disabled }) {
  return (
    <button onClick={onClick} disabled={disabled} className="w-full rounded-lg py-2.5 text-sm font-medium disabled:opacity-50" style={{ backgroundColor: C.primary, color: '#FFFFFF' }}>
      {children}
    </button>
  );
}
function ChipRow({ options, value, onChange }) {
  return (
    <div className="flex flex-wrap gap-2 mt-1">
      {options.map(o => (
        <button key={o} onClick={() => onChange(o)} className="px-3 py-1.5 rounded-full text-xs font-medium border" style={value === o ? { backgroundColor: C.primary, borderColor: C.primary, color: '#FFFFFF' } : { borderColor: C.line, color: C.muted }}>
          {o}
        </button>
      ))}
    </div>
  );
}

function ListView({ tickets, onSelect, filter, setFilter }) {
  const filtered = tickets
    .filter(t => filter === 'open' ? t.currentStage < 6 : filter === 'closed' ? t.currentStage === 6 : true)
    .sort((a, b) => new Date(b.timestamps.raised) - new Date(a.timestamps.raised));

  if (tickets.length === 0) {
    return (
      <div className="text-center py-16">
        <ClipboardList size={28} className="mx-auto mb-3" style={{ color: C.line }} />
        <p className="text-sm" style={{ color: C.muted }}>No tickets yet. Raise the first one to get started.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="flex gap-2 mb-3">
        {['all', 'open', 'closed'].map(f => (
          <button key={f} onClick={() => setFilter(f)} className="px-3 py-1 rounded-full text-xs font-medium capitalize" style={filter === f ? { backgroundColor: C.ink, color: '#FFFFFF' } : { backgroundColor: C.paperMuted, color: C.muted }}>
            {f}
          </button>
        ))}
      </div>
      {filtered.length === 0 ? (
        <p className="text-sm text-center py-10" style={{ color: C.muted }}>No tickets in this view.</p>
      ) : (
        <div className="space-y-2">
          {filtered.map(t => {
            const recurrence = getRecurrence(t, tickets);
            const tone = t.currentStage === 6 ? 'green' : t.currentStage >= 2 ? 'amber' : 'blue';
            return (
              <button key={t.id} onClick={() => onSelect(t.id)} className="w-full text-left bg-white border rounded-xl p-3" style={{ borderColor: C.line }}>
                <div className="flex justify-between items-start gap-2">
                  <div>
                    <p className="text-sm font-semibold" style={{ color: C.ink }}>{t.asset}</p>
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <TicketTag id={t.id} />
                      <span className="text-xs" style={{ color: C.muted }}>{t.section}{t.location ? ' · ' + t.location : ''}</span>
                    </div>
                  </div>
                  <Badge tone={tone}>{STATUS_LABELS[t.currentStage]}</Badge>
                </div>
                <p className="text-xs mt-2" style={{ color: C.muted }}>{t.description}</p>
                <div className="flex justify-between items-center mt-2">
                  <p className="text-xs" style={{ color: C.muted }}>Raised {fmtDateTime(t.timestamps.raised)}</p>
                  {recurrence.count > 1 && <Badge tone="red">Repeat ×{recurrence.count}</Badge>}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RaiseView({ onSubmit, onCancel, busy }) {
  const [section, setSection] = useState('Press');
  const [asset, setAsset] = useState('');
  const [location, setLocation] = useState('');
  const [category, setCategory] = useState('Mechanical');
  const [priority, setPriority] = useState('Medium');
  const [description, setDescription] = useState('');
  const [reporter, setReporter] = useState('');
  const [error, setError] = useState('');

  function handleSubmit() {
    if (!asset.trim() || !description.trim() || !reporter.trim()) {
      setError('Fill in the machine, description, and your name first.');
      return;
    }
    setError('');
    onSubmit({ section, asset: asset.trim(), location: location.trim(), category, priority, description: description.trim(), reporter: reporter.trim() });
  }

  const inputClass = 'w-full border rounded-lg px-3 py-2 text-sm mt-1';

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Section</label>
        <ChipRow options={SECTIONS} value={section} onChange={s => { setSection(s); setAsset(''); }} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Machine / area</label>
        <input value={asset} onChange={e => setAsset(e.target.value)} placeholder="e.g. Press-4" list="machine-suggestions" className={inputClass} style={{ borderColor: C.line }} />
        <datalist id="machine-suggestions">
          {(MACHINE_SUGGESTIONS[section] || []).map(m => <option key={m} value={m} />)}
        </datalist>
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Location / bay (optional)</label>
        <input value={location} onChange={e => setLocation(e.target.value)} placeholder="e.g. Bay 3" className={inputClass} style={{ borderColor: C.line }} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Issue category</label>
        <ChipRow options={CATEGORIES} value={category} onChange={setCategory} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Priority</label>
        <ChipRow options={PRIORITIES} value={priority} onChange={setPriority} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>BD details</label>
        <textarea value={description} onChange={e => setDescription(e.target.value)} rows={3} placeholder="What's wrong, and since when?" className={inputClass} style={{ borderColor: C.line }} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Your name</label>
        <input value={reporter} onChange={e => setReporter(e.target.value)} placeholder="e.g. Ramesh Kumar" className={inputClass} style={{ borderColor: C.line }} />
      </div>
      {error && <p className="text-xs" style={{ color: C.rust }}>{error}</p>}
      <div className="flex gap-2 pt-2">
        <button onClick={onCancel} className="flex-1 border rounded-lg py-2.5 text-sm font-medium" style={{ borderColor: C.line, color: C.muted }}>Cancel</button>
        <div className="flex-1">
          <PrimaryButton onClick={handleSubmit} disabled={busy}>{busy ? 'Submitting…' : 'Submit ticket'}</PrimaryButton>
        </div>
      </div>
    </div>
  );
}

function getBanner(ticket) {
  const stage = ticket.currentStage;
  if (stage === 6) return { icon: Check, bg: C.primaryTint, color: C.primary, text: 'Resolved and verified' + (ticket.timestamps.resolved && ticket.timestamps.raised ? ', took ' + fmtDuration(ticket.timestamps.raised, ticket.timestamps.resolved) : '') };
  if (stage === 0) return { icon: Clock, bg: '#E7EEF3', color: '#2E5A78', text: 'Waiting for the maintenance team to acknowledge' };
  if (stage === 4) return { icon: Wrench, bg: C.amberTint, color: C.amber, text: 'Machine is running again — root cause write-up pending' };
  if (stage === 5) return { icon: Search, bg: C.amberTint, color: C.amber, text: 'Root cause logged — ready for final verification' };
  return { icon: Wrench, bg: C.amberTint, color: C.amber, text: STATUS_LABELS[stage] + ', technician is on it' };
}

function DetailView({ ticket, allTickets, onBack, onAdvance, busy }) {
  const [immediateCorrection, setImmediateCorrection] = useState('');
  const [rootCause, setRootCause] = useState('');
  const [preventiveAction, setPreventiveAction] = useState('');
  const [sheetsAfterSanding, setSheetsAfterSanding] = useState('');
  const [matSource, setMatSource] = useState('store');
  const [matName, setMatName] = useState('');
  const [matQty, setMatQty] = useState('');
  const [matCost, setMatCost] = useState('');
  const [matBin, setMatBin] = useState('');
  const [matVendor, setMatVendor] = useState('');
  const [matPo, setMatPo] = useState('');
  const [rating, setRating] = useState(0);
  const [formError, setFormError] = useState('');

  const recurrence = getRecurrence(ticket, allTickets);
  const banner = getBanner(ticket);
  const inputClass = 'w-full border rounded-lg px-3 py-2 text-sm';

  function handleAcknowledge() {
    onAdvance({ currentStage: 1, timestamps: { ...ticket.timestamps, ack: nowIso() } });
  }
  function handleMaterial() {
    if (matSource !== 'none' && !matName.trim()) {
      setFormError('Enter the material name, or choose "Not needed."');
      return;
    }
    setFormError('');
    const material = matSource === 'none' ? null : (matSource === 'store'
      ? { source: 'store', name: matName.trim(), qty: matQty, cost: matCost.trim(), bin: matBin.trim() }
      : { source: 'purchase', name: matName.trim(), qty: matQty, cost: matCost.trim(), vendor: matVendor.trim(), po: matPo.trim() });
    onAdvance({ currentStage: 2, timestamps: { ...ticket.timestamps, material: nowIso() }, material });
  }
  function handleStartRepair() {
    onAdvance({ currentStage: 3, timestamps: { ...ticket.timestamps, repair: nowIso() } });
  }
  function handleResolve() {
    if (!immediateCorrection.trim()) { setFormError('Describe what was done to get it running again.'); return; }
    setFormError('');
    onAdvance({ currentStage: 4, timestamps: { ...ticket.timestamps, resolved: nowIso() }, immediateCorrection: immediateCorrection.trim() });
  }
  function handleRootCause() {
    if (!rootCause.trim()) { setFormError('Enter a root cause first.'); return; }
    setFormError('');
    onAdvance({
      currentStage: 5,
      timestamps: { ...ticket.timestamps, diagnosis: nowIso() },
      rootCause: rootCause.trim(),
      preventiveAction: preventiveAction.trim(),
      sheetsAfterSanding: sheetsAfterSanding.trim(),
    });
  }
  function handleClose() {
    if (!rating) { setFormError('Tap a star to rate this resolution.'); return; }
    setFormError('');
    onAdvance({ currentStage: 6, timestamps: { ...ticket.timestamps, closed: nowIso() }, rating });
  }
  function handleReopen() {
    onAdvance({
      currentStage: 3,
      timestamps: { ...ticket.timestamps, resolved: null, diagnosis: null, closed: null },
      immediateCorrection: '', rootCause: '', preventiveAction: '', rating: null,
    });
  }

  return (
    <div>
      <button onClick={onBack} className="flex items-center gap-1 text-sm font-medium mb-3" style={{ color: C.primary }}>
        <ChevronLeft size={16} /> All tickets
      </button>

      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <TicketTag id={ticket.id} />
        <Badge tone="neutral">{ticket.section}</Badge>
        <Badge tone="neutral">{ticket.category}</Badge>
        <Badge tone={ticket.priority === 'Critical' ? 'red' : ticket.priority === 'High' ? 'amber' : 'neutral'}>{ticket.priority}</Badge>
      </div>
      <h2 className="text-base font-semibold mt-1.5" style={{ color: C.ink }}>{ticket.asset}</h2>
      <p className="text-xs mt-0.5" style={{ color: C.muted }}>{ticket.location || 'No location set'} · reported by {ticket.reporter}</p>
      <p className="text-sm mt-2" style={{ color: C.ink }}>{ticket.description}</p>

      <div className="mt-3">
        <div className="rounded-lg px-3 py-2 text-sm font-medium mb-2 flex items-center gap-2" style={{ backgroundColor: banner.bg, color: banner.color }}>
          <banner.icon size={16} /> {banner.text}
        </div>

        {ticket.currentStage === 6 && recurrence.count > 1 && (
          <div className="rounded-lg px-3 py-2 text-sm font-medium mb-2 flex gap-2 items-start" style={{ backgroundColor: C.rustTint, color: C.rust }}>
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <span>Repeat issue, reported {recurrence.count} times for this machine and category.</span>
          </div>
        )}
      </div>

      <div className="my-4">
        {STAGES.map((s, idx) => {
          const done = idx < ticket.currentStage || (idx === ticket.currentStage && ticket.currentStage === 6);
          const active = idx === ticket.currentStage && ticket.currentStage !== 6;
          const ts = ticket.timestamps[s.key];
          const Icon = done ? Check : s.icon;
          const dotStyle = done
            ? { backgroundColor: C.primary, borderColor: C.primary, color: '#FFFFFF' }
            : active
            ? { backgroundColor: '#FFFFFF', borderColor: C.amber, color: C.amber }
            : { backgroundColor: C.paperMuted, borderColor: C.line, color: C.muted };
          return (
            <div key={s.key} className="flex gap-3 relative pb-4 last:pb-0">
              {idx < STAGES.length - 1 && (
                <div className="absolute top-6 bottom-0 w-0.5" style={{ left: '11px', backgroundColor: idx < ticket.currentStage ? C.primary : C.line }} />
              )}
              <div className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 relative z-10 border-2" style={dotStyle}>
                <Icon size={12} />
              </div>
              <div>
                <p className="text-sm font-medium" style={{ color: idx > ticket.currentStage ? C.muted : C.ink }}>{s.label}</p>
                <p className="text-xs" style={{ color: C.muted }}>{ts ? fmtDateTime(ts) : active ? 'In progress' : 'Pending'}</p>
              </div>
            </div>
          );
        })}
      </div>

      {ticket.immediateCorrection && (
        <InfoCard label="Immediate correction">
          <p className="text-sm" style={{ color: C.ink }}>{ticket.immediateCorrection}</p>
        </InfoCard>
      )}

      {ticket.material && (
        <InfoCard label="Material used">
          <Row label="Item" value={ticket.material.name} />
          {ticket.material.qty && <Row label="Quantity" value={ticket.material.qty} />}
          <Row label="Source" value={ticket.material.source === 'store' ? 'Store stock' + (ticket.material.bin ? ', bin ' + ticket.material.bin : '') : 'New purchase' + (ticket.material.vendor ? ', ' + ticket.material.vendor : '')} />
          {ticket.material.po && <Row label="PO number" value={ticket.material.po} />}
          {ticket.material.cost && <Row label="Cost" value={ticket.material.cost} />}
        </InfoCard>
      )}

      {ticket.rootCause && (
        <InfoCard label="Root cause (why-why)">
          <p className="text-sm" style={{ color: C.ink }}>{ticket.rootCause}</p>
        </InfoCard>
      )}

      {ticket.preventiveAction && (
        <InfoCard label="Preventive action">
          <p className="text-sm" style={{ color: C.ink }}>{ticket.preventiveAction}</p>
        </InfoCard>
      )}

      {ticket.sheetsAfterSanding && (
        <InfoCard label="Problem observed after how many sheets sanding">
          <p className="text-sm" style={{ color: C.ink }}>{ticket.sheetsAfterSanding}</p>
        </InfoCard>
      )}

      {ticket.currentStage >= 1 && (
        <InfoCard label="History on this asset">
          <p className="text-sm" style={{ color: C.ink }}>
            {recurrence.count > 1 ? 'Reported ' + recurrence.count + ' times for this machine and category.' : 'First time this fault has been reported on this asset.'}
          </p>
        </InfoCard>
      )}

      {ticket.rating ? (
        <InfoCard label="Requester rating">
          <div className="flex gap-0.5">
            {[1, 2, 3, 4, 5].map(i => (
              <Star key={i} size={16} style={i <= ticket.rating ? { fill: C.amber, color: C.amber } : { color: C.line }} />
            ))}
          </div>
        </InfoCard>
      ) : null}

      <div className="border-t pt-3 mt-3" style={{ borderColor: C.line }}>
        {ticket.currentStage === 0 && (
          <PrimaryButton onClick={handleAcknowledge} disabled={busy}>Acknowledge ticket</PrimaryButton>
        )}

        {ticket.currentStage === 1 && (
          <div className="space-y-2">
            <label className="text-xs font-medium" style={{ color: C.muted }}>Material needed?</label>
            <div className="flex flex-wrap gap-2">
              {[['store', 'From store'], ['purchase', 'New purchase'], ['none', 'Not needed']].map(([val, lbl]) => (
                <button key={val} onClick={() => setMatSource(val)} className="flex-1 border rounded-lg py-2 text-xs font-medium" style={matSource === val ? { borderColor: C.primary, backgroundColor: C.primaryTint, color: C.primary } : { borderColor: C.line, color: C.muted }}>
                  {lbl}
                </button>
              ))}
            </div>
            {matSource !== 'none' && (
              <>
                <input value={matName} onChange={e => setMatName(e.target.value)} placeholder="Material name" className={inputClass} style={{ borderColor: C.line }} />
                <div className="flex gap-2">
                  <input value={matQty} onChange={e => setMatQty(e.target.value)} placeholder="Quantity" className={inputClass} style={{ borderColor: C.line }} />
                  <input value={matCost} onChange={e => setMatCost(e.target.value)} placeholder="Cost (optional)" className={inputClass} style={{ borderColor: C.line }} />
                </div>
                {matSource === 'store' ? (
                  <input value={matBin} onChange={e => setMatBin(e.target.value)} placeholder="Store bin (optional)" className={inputClass} style={{ borderColor: C.line }} />
                ) : (
                  <div className="flex gap-2">
                    <input value={matVendor} onChange={e => setMatVendor(e.target.value)} placeholder="Vendor" className={inputClass} style={{ borderColor: C.line }} />
                    <input value={matPo} onChange={e => setMatPo(e.target.value)} placeholder="PO number" className={inputClass} style={{ borderColor: C.line }} />
                  </div>
                )}
              </>
            )}
            {formError && <p className="text-xs" style={{ color: C.rust }}>{formError}</p>}
            <PrimaryButton onClick={handleMaterial} disabled={busy}>Save material</PrimaryButton>
          </div>
        )}

        {ticket.currentStage === 2 && (
          <PrimaryButton onClick={handleStartRepair} disabled={busy}>Start repair</PrimaryButton>
        )}

        {ticket.currentStage === 3 && (
          <div className="space-y-2">
            <label className="text-xs font-medium" style={{ color: C.muted }}>Immediate correction — what got it running again?</label>
            <textarea value={immediateCorrection} onChange={e => setImmediateCorrection(e.target.value)} rows={2} placeholder="e.g. Replaced timing belt" className={inputClass} style={{ borderColor: C.line }} />
            {formError && <p className="text-xs" style={{ color: C.rust }}>{formError}</p>}
            <PrimaryButton onClick={handleResolve} disabled={busy}>Mark resolved</PrimaryButton>
          </div>
        )}

        {ticket.currentStage === 4 && (
          <div className="space-y-2">
            <label className="text-xs font-medium" style={{ color: C.muted }}>Root cause (why-why)</label>
            <textarea value={rootCause} onChange={e => setRootCause(e.target.value)} rows={3} placeholder="Why did this actually happen?" className={inputClass} style={{ borderColor: C.line }} />
            <label className="text-xs font-medium" style={{ color: C.muted }}>Preventive action (optional)</label>
            <textarea value={preventiveAction} onChange={e => setPreventiveAction(e.target.value)} rows={2} placeholder="What should change so this doesn't recur?" className={inputClass} style={{ borderColor: C.line }} />
            {ticket.section === 'Sanding' && (
              <>
                <label className="text-xs font-medium" style={{ color: C.muted }}>Problem observed after how many sheets sanding (optional)</label>
                <input value={sheetsAfterSanding} onChange={e => setSheetsAfterSanding(e.target.value)} placeholder="e.g. 1200 sheets" className={inputClass} style={{ borderColor: C.line }} />
              </>
            )}
            {formError && <p className="text-xs" style={{ color: C.rust }}>{formError}</p>}
            <PrimaryButton onClick={handleRootCause} disabled={busy}>Save root cause</PrimaryButton>
          </div>
        )}

        {ticket.currentStage === 5 && (
          <div className="space-y-2">
            <label className="text-xs font-medium" style={{ color: C.muted }}>Rate this resolution</label>
            <div className="flex gap-1">
              {[1, 2, 3, 4, 5].map(i => (
                <button key={i} onClick={() => setRating(i)}>
                  <Star size={22} style={i <= rating ? { fill: C.amber, color: C.amber } : { color: C.line }} />
                </button>
              ))}
            </div>
            {formError && <p className="text-xs" style={{ color: C.rust }}>{formError}</p>}
            <PrimaryButton onClick={handleClose} disabled={busy}>Verify and close</PrimaryButton>
          </div>
        )}

        {ticket.currentStage === 6 && (
          <button onClick={handleReopen} disabled={busy} className="w-full border rounded-lg py-2.5 text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50" style={{ borderColor: C.line, color: C.ink }}>
            <RotateCcw size={15} /> Reopen, issue isn't fixed
          </button>
        )}
      </div>
    </div>
  );
}

function ProductionLogForm({ onSubmit, onCancel, busy }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [size, setSize] = useState('');
  const [texture, setTexture] = useState('Glossy');
  const [produced, setProduced] = useState('');
  const [rejected, setRejected] = useState('0');
  const [rejectReason, setRejectReason] = useState('');
  const [loggedBy, setLoggedBy] = useState('');
  const [error, setError] = useState('');

  function handleSubmit() {
    if (!size.trim() || !produced || !loggedBy.trim()) {
      setError('Fill in size, quantity produced, and your name.');
      return;
    }
    if (Number(rejected) > 0 && !rejectReason) {
      setError('Choose a reject reason.');
      return;
    }
    setError('');
    onSubmit({
      date, size: size.trim(), texture,
      produced: Number(produced), rejected: Number(rejected) || 0,
      rejectReason: Number(rejected) > 0 ? rejectReason : '',
      loggedBy: loggedBy.trim(),
    });
  }

  const inputClass = 'w-full border rounded-lg px-3 py-2 text-sm mt-1';

  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Date</label>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className={inputClass} style={{ borderColor: C.line }} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Sheet size</label>
        <input value={size} onChange={e => setSize(e.target.value)} placeholder="e.g. 8×4 ft or 2440×1220mm" className={inputClass} style={{ borderColor: C.line }} />
      </div>
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Texture</label>
        <ChipRow options={TEXTURES} value={texture} onChange={setTexture} />
      </div>
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-xs font-medium" style={{ color: C.muted }}>Produced</label>
          <input value={produced} onChange={e => setProduced(e.target.value)} placeholder="0" inputMode="numeric" className={inputClass} style={{ borderColor: C.line }} />
        </div>
        <div className="flex-1">
          <label className="text-xs font-medium" style={{ color: C.muted }}>Rejected</label>
          <input value={rejected} onChange={e => setRejected(e.target.value)} placeholder="0" inputMode="numeric" className={inputClass} style={{ borderColor: C.line }} />
        </div>
      </div>
      {Number(rejected) > 0 && (
        <div>
          <label className="text-xs font-medium" style={{ color: C.muted }}>Reject reason</label>
          <ChipRow options={REJECT_REASONS} value={rejectReason} onChange={setRejectReason} />
        </div>
      )}
      <div>
        <label className="text-xs font-medium" style={{ color: C.muted }}>Your name</label>
        <input value={loggedBy} onChange={e => setLoggedBy(e.target.value)} placeholder="e.g. Satyendra Chauhan" className={inputClass} style={{ borderColor: C.line }} />
      </div>
      {error && <p className="text-xs" style={{ color: C.rust }}>{error}</p>}
      <div className="flex gap-2 pt-2">
        <button onClick={onCancel} className="flex-1 border rounded-lg py-2.5 text-sm font-medium" style={{ borderColor: C.line, color: C.muted }}>Cancel</button>
        <div className="flex-1">
          <PrimaryButton onClick={handleSubmit} disabled={busy}>{busy ? 'Saving…' : 'Log entry'}</PrimaryButton>
        </div>
      </div>
    </div>
  );
}

function ProductionListView({ production, onLogNew }) {
  const sorted = [...production].sort((a, b) => new Date(b.date) - new Date(a.date));
  return (
    <div>
      <button onClick={onLogNew} className="w-full border-dashed border-2 rounded-lg py-3 text-sm font-medium mb-3 flex items-center justify-center gap-2" style={{ borderColor: C.line, color: C.primary }}>
        <Plus size={15} /> Log production
      </button>
      {sorted.length === 0 ? (
        <p className="text-sm text-center py-10" style={{ color: C.muted }}>No production logged yet.</p>
      ) : (
        <div className="space-y-2">
          {sorted.map((p, i) => (
            <div key={i} className="bg-white border rounded-xl p-3" style={{ borderColor: C.line }}>
              <div className="flex justify-between items-start gap-2">
                <p className="text-sm font-semibold" style={{ color: C.ink }}>{p.size} · {p.texture}</p>
                <span className="text-xs" style={{ color: C.muted }}>{p.date}</span>
              </div>
              <div className="flex gap-4 mt-1.5">
                <span className="text-xs" style={{ color: C.muted }}>Produced <b style={{ color: C.ink, fontWeight: 500 }}>{p.produced}</b></span>
                {Number(p.rejected) > 0 && <span className="text-xs" style={{ color: C.rust }}>Rejected <b style={{ fontWeight: 500 }}>{p.rejected}</b> ({p.rejectReason})</span>}
              </div>
              <p className="text-xs mt-1" style={{ color: C.muted }}>Logged by {p.loggedBy}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DashboardGate({ onUnlock }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  function submit() {
    if (code.trim().toUpperCase() === DASHBOARD_PASSCODE) {
      onUnlock();
    } else {
      setError('Incorrect code.');
    }
  }
  return (
    <div className="text-center py-14 px-2">
      <Lock size={26} className="mx-auto mb-3" style={{ color: C.line }} />
      <p className="text-sm font-medium mb-1" style={{ color: C.ink }}>Restricted to plant leadership</p>
      <p className="text-xs mb-4" style={{ color: C.muted }}>Enter the access code to view breakdown and production analytics.</p>
      <input value={code} onChange={e => setCode(e.target.value)} onKeyDown={e => e.key === 'Enter' && submit()} placeholder="Access code" className="w-full border rounded-lg px-3 py-2 text-sm text-center mb-2" style={{ borderColor: C.line }} />
      {error && <p className="text-xs mb-2" style={{ color: C.rust }}>{error}</p>}
      <button onClick={submit} className="rounded-lg py-2 px-6 text-sm font-medium" style={{ backgroundColor: C.primary, color: '#FFFFFF' }}>Unlock</button>
    </div>
  );
}

function Dashboard({ tickets, production, unlocked, onUnlock, onExport }) {
  if (!unlocked) return <DashboardGate onUnlock={onUnlock} />;

  const stats = computeInsights(tickets);
  const bd = computeBdStats(tickets);
  const pm = computePmCandidates(tickets);
  const prod = computeProductionStats(production);

  return (
    <div className="space-y-5">
      <button onClick={onExport} className="w-full border rounded-lg py-2.5 text-sm font-medium flex items-center justify-center gap-2" style={{ borderColor: C.line, color: C.ink }}>
        <Download size={15} /> Export to Excel
      </button>

      <div>
        <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Breakdown summary</p>
        <div className="grid grid-cols-2 gap-3">
          <StatCard label="Total issues reported" value={bd.totalIssues} />
          <StatCard label="Total breakdown" value={bd.totalHrs + ' hrs'} />
          <StatCard label="Avg response time" value={stats.avgResponseMins != null ? fmtMinutes(stats.avgResponseMins) : '—'} />
          <StatCard label="Resolved this month" value={stats.resolvedThisMonth} />
        </div>
      </div>

      {bd.bySection.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Section-wise breakdown</p>
          <div className="space-y-2">
            {bd.bySection.map((s, i) => (
              <div key={i} className="flex justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: C.paperMuted }}>
                <span style={{ color: C.ink }}>{s.section}</span>
                <span style={{ color: C.muted }}>{fmtMinutes(s.min)} · {s.count} issue{s.count === 1 ? '' : 's'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Preventive maintenance candidates</p>
        {pm.length === 0 ? (
          <p className="text-xs" style={{ color: C.muted }}>No machine has crossed {PM_THRESHOLD} breakdowns yet.</p>
        ) : (
          <div className="space-y-2">
            {pm.map((g, i) => (
              <div key={i} className="rounded-lg px-3 py-2" style={{ backgroundColor: C.rustTint }}>
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium" style={{ color: C.rust }}>{g.asset}</span>
                  <Badge tone="red">{g.count} breakdowns</Badge>
                </div>
                <p className="text-xs mt-0.5" style={{ color: C.rust }}>{g.section} · last on {fmtDateTime(g.lastDate)} — schedule preventive maintenance</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {stats.recurring.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Top recurring faults</p>
          <div className="space-y-2">
            {stats.recurring.slice(0, 6).map((g, i) => (
              <div key={i} className="flex justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: C.paperMuted }}>
                <span style={{ color: C.ink }}>{g.asset}, {g.category}</span>
                <span style={{ color: C.muted }}>×{g.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.avgByCategory.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Avg resolution time by category</p>
          <div className="space-y-2">
            {stats.avgByCategory.map((c, i) => (
              <div key={i} className="flex justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: C.paperMuted }}>
                <span style={{ color: C.ink }}>{c.category}</span>
                <span style={{ color: C.muted }}>{fmtMinutes(c.avgMins)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Production summary</p>
        <div className="grid grid-cols-2 gap-3">
          <StatCard label="Sheets produced" value={prod.totalProduced} />
          <StatCard label="Reject rate" value={prod.rejectRate + '%'} />
        </div>
      </div>

      {prod.byTexture.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Production by texture</p>
          <div className="space-y-2">
            {prod.byTexture.map((t, i) => (
              <div key={i} className="flex justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: C.paperMuted }}>
                <span style={{ color: C.ink }}>{t.texture}</span>
                <span style={{ color: C.muted }}>{t.produced} made · {t.rejected} rejected</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {prod.byReason.length > 0 && (
        <div>
          <p className="text-xs font-medium mb-2" style={{ color: C.ink }}>Top rejection reasons</p>
          <div className="space-y-2">
            {prod.byReason.map((r, i) => (
              <div key={i} className="flex justify-between text-sm rounded-lg px-3 py-2" style={{ backgroundColor: C.paperMuted }}>
                <span style={{ color: C.ink }}>{r.reason}</span>
                <span style={{ color: C.muted }}>{r.count} sheets</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MaintenanceTracker() {
  const [tickets, setTickets] = useState([]);
  const [production, setProduction] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('tickets');
  const [ticketView, setTicketView] = useState('list');
  const [showProductionForm, setShowProductionForm] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [filter, setFilter] = useState('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dashboardUnlocked, setDashboardUnlocked] = useState(false);

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      const tRes = await window.storage.get('tickets', true).catch(() => null);
      const pRes = await window.storage.get('production', true).catch(() => null);
      const tParsed = tRes && tRes.value ? JSON.parse(tRes.value) : [];
      const pParsed = pRes && pRes.value ? JSON.parse(pRes.value) : [];
      setTickets(Array.isArray(tParsed) ? tParsed : []);
      setProduction(Array.isArray(pParsed) ? pParsed : []);
    } catch (e) {
      setTickets([]);
      setProduction([]);
    }
    setLoading(false);
  }

  async function persistTickets(updated) {
    setBusy(true); setError('');
    try {
      const res = await window.storage.set('tickets', JSON.stringify(updated), true);
      if (!res) throw new Error('save failed');
      setTickets(updated);
      setBusy(false);
      return true;
    } catch (e) {
      setError('Could not save changes. Check your connection and try again.');
      setBusy(false);
      return false;
    }
  }

  async function persistProduction(updated) {
    setBusy(true); setError('');
    try {
      const res = await window.storage.set('production', JSON.stringify(updated), true);
      if (!res) throw new Error('save failed');
      setProduction(updated);
      setBusy(false);
      return true;
    } catch (e) {
      setError('Could not save changes. Check your connection and try again.');
      setBusy(false);
      return false;
    }
  }

  function handleCreateTicket(fields) {
    const newTicket = {
      id: uid(),
      section: fields.section,
      asset: fields.asset,
      location: fields.location,
      category: fields.category,
      priority: fields.priority,
      description: fields.description,
      reporter: fields.reporter,
      currentStage: 0,
      timestamps: { raised: nowIso() },
      immediateCorrection: '',
      rootCause: '',
      preventiveAction: '',
      sheetsAfterSanding: '',
      material: null,
      rating: null,
    };
    persistTickets([...tickets, newTicket]).then(success => {
      if (success) {
        setSelectedId(newTicket.id);
        setTicketView('detail');
      }
    });
  }

  function handleAdvanceTicket(patch) {
    persistTickets(tickets.map(t => (t.id === selectedId ? { ...t, ...patch } : t)));
  }

  function handleLogProduction(fields) {
    persistProduction([...production, fields]).then(success => {
      if (success) setShowProductionForm(false);
    });
  }

  function handleExport() {
    const bdRows = tickets.map((t, i) => ({
      'Sr No': i + 1,
      'Date': t.timestamps.raised ? t.timestamps.raised.slice(0, 10) : '',
      'Month': t.timestamps.raised ? monthLabel(t.timestamps.raised) : '',
      'Section': t.section || '',
      'Machine / Area': t.asset,
      'Issue Category': t.category,
      'BD (Min)': bdMinutesOf(t) != null ? Math.round(bdMinutesOf(t)) : '',
      'BD (Hrs)': bdMinutesOf(t) != null ? +(bdMinutesOf(t) / 60).toFixed(2) : '',
      'BD Details': t.description,
      'Immediate Correction(Filled by maint.)': t.immediateCorrection || '',
      'Root Cause (Why-Why) (Filled by maint.)': t.rootCause || '',
      'Preventive Action(Filled by Maint)': t.preventiveAction || '',
      'Problem observed after how many sheet  sanding': t.sheetsAfterSanding || '',
    }));
    const prodRows = production.map((p, i) => ({
      'Sr No': i + 1,
      'Date': p.date,
      'Size': p.size,
      'Texture': p.texture,
      'Produced': p.produced,
      'Rejected': p.rejected,
      'Reject Reason': p.rejectReason || '',
      'Logged By': p.loggedBy,
    }));
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(bdRows), 'BD Tracker');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(prodRows), 'Production');
    const dateStr = new Date().toISOString().slice(0, 10);
    XLSX.writeFile(wb, 'greenlam-tracker-export-' + dateStr + '.xlsx');
  }

  function handleHeaderAdd() {
    if (activeTab === 'tickets') { setTicketView('raise'); }
    else if (activeTab === 'production') { setShowProductionForm(true); }
  }

  const selectedTicket = tickets.find(t => t.id === selectedId);

  return (
    <div className="min-h-screen" style={{ backgroundColor: C.paperMuted }}>
      <div className="max-w-md mx-auto min-h-screen flex flex-col" style={{ backgroundColor: C.paper }}>
        <header className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: C.line, backgroundColor: '#FFFFFF' }}>
          <div className="flex items-center gap-2">
            <ClipboardList size={18} style={{ color: C.primary }} />
            <p className="text-sm font-semibold" style={{ color: C.ink }}>Greenlam maintenance tracker</p>
          </div>
          {activeTab !== 'dashboard' && (
            <button onClick={handleHeaderAdd} className="rounded-full p-1.5" style={{ backgroundColor: C.primary, color: '#FFFFFF' }}>
              <Plus size={16} />
            </button>
          )}
        </header>

        <main className="flex-1 p-4 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-16"><Loader2 className="animate-spin" size={22} style={{ color: C.line }} /></div>
          ) : activeTab === 'tickets' ? (
            ticketView === 'raise' ? (
              <RaiseView onSubmit={handleCreateTicket} onCancel={() => setTicketView('list')} busy={busy} />
            ) : ticketView === 'detail' ? (
              selectedTicket ? (
                <DetailView ticket={selectedTicket} allTickets={tickets} onBack={() => setTicketView('list')} onAdvance={handleAdvanceTicket} busy={busy} />
              ) : (
                <p className="text-sm text-center py-10" style={{ color: C.muted }}>Ticket not found.</p>
              )
            ) : (
              <ListView tickets={tickets} onSelect={id => { setSelectedId(id); setTicketView('detail'); }} filter={filter} setFilter={setFilter} />
            )
          ) : activeTab === 'production' ? (
            showProductionForm ? (
              <ProductionLogForm onSubmit={handleLogProduction} onCancel={() => setShowProductionForm(false)} busy={busy} />
            ) : (
              <ProductionListView production={production} onLogNew={() => setShowProductionForm(true)} />
            )
          ) : (
            <Dashboard tickets={tickets} production={production} unlocked={dashboardUnlocked} onUnlock={() => setDashboardUnlocked(true)} onExport={handleExport} />
          )}
          {error && <p className="text-xs text-center mt-3" style={{ color: C.rust }}>{error}</p>}
        </main>

        <nav className="flex border-t" style={{ borderColor: C.line, backgroundColor: '#FFFFFF' }}>
          <button onClick={() => setActiveTab('tickets')} className="flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs" style={{ color: activeTab === 'tickets' ? C.primary : C.muted, fontWeight: activeTab === 'tickets' ? 600 : 400 }}>
            <ClipboardList size={18} /> Tickets
          </button>
          <button onClick={() => setActiveTab('production')} className="flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs" style={{ color: activeTab === 'production' ? C.primary : C.muted, fontWeight: activeTab === 'production' ? 600 : 400 }}>
            <Layers size={18} /> Production
          </button>
          <button onClick={() => setActiveTab('dashboard')} className="flex-1 flex flex-col items-center gap-0.5 py-2.5 text-xs" style={{ color: activeTab === 'dashboard' ? C.primary : C.muted, fontWeight: activeTab === 'dashboard' ? 600 : 400 }}>
            <BarChart3 size={18} /> Dashboard
          </button>
        </nav>
      </div>
    </div>
  );
}
