@extends('layouts.app', ['activePage' => 'alerts.html'])
@section('title', 'Alerts')
@section('content')
<div class="doc" x-data="{
  sev: '', unacked: false, grouped: true, q: '', openKey: null, notes: {},
  all: structuredClone(XG.alerts),
  get filtered() { const q = this.q.toLowerCase(); return this.all.filter(a => (!this.sev || a.sev === this.sev) && (!this.unacked || !a.acked) && (!q || (a.pc + a.title + a.rule).toLowerCase().includes(q))); },
  get rows() { return this.grouped ? xgGroup(this.filtered) : this.filtered.map(a => ({ ...a, key: 'a' + a.id, count: 1, items: [a] })); },
  get waiting() { return xgGroup(this.all.filter(a => !a.acked)).length; },
  n(s) { return this.all.filter(a => a.sev === s).length; },
  ack(r) { const note = (this.notes[r.key] || '').trim() || 'Reviewed.'; r.items.forEach(i => { const a = this.all.find(x => x.id === i.id); a.acked = true; a.by = 'KUET admin'; a.note = note; }); this.openKey = null; $store.toasts.add(r.pc + ': marked as reviewed.', 'ok'); }
}"><div class="optbar"><span class="otitle">Alerts</span><span class="osub"><span x-text="waiting"></span> waiting for review. Repeated alerts are grouped.</span><span class="grow"></span>
      <select class="select select-sm" style="width:260px" aria-label="Session"><option>Exam · CSER (running)</option><option>All sessions</option><option>CSE 1101 practice · Nov 07</option></select>
    </div><div class="canvas ">
  

  <div class="toolbar">
    <div class="pills" role="group" aria-label="Severity">
      <button class="pill" :aria-pressed="sev === ''" @click="sev = ''">All <span class="n" x-text="all.length"></span></button>
      <button class="pill" :aria-pressed="sev === 'critical'" @click="sev = 'critical'">Critical <span class="n" x-text="n('critical')"></span></button>
      <button class="pill" :aria-pressed="sev === 'high'" @click="sev = 'high'">High <span class="n" x-text="n('high')"></span></button>
      <button class="pill" :aria-pressed="sev === 'medium'" @click="sev = 'medium'">Medium <span class="n" x-text="n('medium')"></span></button>
      <button class="pill" :aria-pressed="sev === 'low'" @click="sev = 'low'">Low <span class="n" x-text="n('low')"></span></button>
    </div>
    <input class="input input-sm" style="width:220px;margin-left:8px" placeholder="Search PC or alert" x-model="q">
    <span class="grow"></span>
    <label class="check small"><span class="switch"><input type="checkbox" x-model="unacked"><i></i></span> Unreviewed only</label>
    <label class="check small"><span class="switch"><input type="checkbox" x-model="grouped"><i></i></span> Group repeats</label>
  </div>

  <template x-for="r in rows" :key="r.key">
    <div class="msg" :class="{ unread: !r.acked }">
      <button class="msg-row" @click="openKey = openKey === r.key ? null : r.key" :aria-expanded="openKey === r.key">
        <span class="sev" :class="r.sev" x-text="r.sev"></span>
        <span><span class="t"><span x-text="r.title"></span> <span class="count" x-show="r.count > 1" x-text="'×' + r.count"></span></span><span class="m"><b x-text="r.pc"></b> · <span x-text="r.user"></span> · <span class="mono" x-text="r.rule"></span></span></span>
        <span class="when" x-text="xgAgo(r.ago)"></span>
        <span><span class="chip alert" x-show="!r.acked">Needs review</span><span class="small muted" x-show="r.acked">Reviewed</span></span>
      </button>
      <div x-show="openKey === r.key" x-cloak>
        <template x-if="r.count > 1"><div><template x-for="i in r.items" :key="i.id"><div class="msg-sub"><span class="mono muted" x-text="i.at"></span><span x-text="i.title"></span><span class="muted" x-text="xgAgo(i.ago)"></span></div></template></div></template>
        <div class="msg-detail" style="padding-left:20px">
          <template x-if="r.acked"><div class="note"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg><div><b x-text="'Reviewed by ' + (r.by || 'KUET admin')"></b><br><span x-text="r.note || 'No note.'"></span></div></div></template>
          <template x-if="!r.acked">
            <div class="stack" style="--gap:10px;max-width:640px">
              <label class="field"><span>Note (optional)</span><textarea class="textarea" rows="2" placeholder="What did you find out?" x-model="notes[r.key]"></textarea></label>
              <div class="row"><button class="btn btn-solid" @click="ack(r)" x-text="r.count > 1 ? 'Mark all ' + r.count + ' as reviewed' : 'Mark as reviewed'"></button><a class="btn btn-quiet" :href="'index.html#pc=' + r.pcId">Show PC in Live lab</a>
                <span class="pills" style="margin-left:auto"><button class="pill" @click="notes[r.key] = 'False alarm.'">False alarm</button><button class="pill" @click="notes[r.key] = 'Spoke to the student.'">Spoke to student</button></span></div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </template>
  <div class="empty-state" x-show="!rows.length"><b>Nothing matches</b>Try clearing a filter.</div>
</div></div>
@endsection
