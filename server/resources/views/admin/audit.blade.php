@extends('layouts.app', ['activePage' => 'audit.html'])
@section('title', 'Audit log')
@section('content')
@php
  $liveAudit = isset($entries) && $entries->count() ? $entries->getCollection()->map(function ($e) {
      return [
          'id' => $e->id,
          't' => $e->created_at?->format('M d H:i') ?? 'Recently',
          'who' => $e->user?->name ?? 'System',
          'act' => $e->action,
          'target' => $e->subject_type ? ($e->subject_type . ($e->subject_id ? '#' . $e->subject_id : '')) : 'Lab',
          'sum' => ucfirst(str_replace(['.', '_'], ' ', $e->action)),
          'json' => e(json_encode($e->details ?? [], JSON_UNESCAPED_SLASHES)),
          'ip' => $e->ip ?? '—',
      ];
  })->values()->all() : null;
@endphp
<script>
window.XG_AUDIT_PAGE = {
  rows: @json($liveAudit),
};
</script>
<div class="doc" x-data="{
  fam: '', q: '', openId: null,
  rows: window.XG_AUDIT_PAGE.rows !== null ? window.XG_AUDIT_PAGE.rows : [
    { id: 1, t: 'Today 12:03', who: 'KUET Admin', act: 'screen.view_live', target: 'Rupom2', sum: 'Started a live screen view', json: '{&quot;pc&quot;:&quot;Rupom2&quot;,&quot;mode&quot;:&quot;live&quot;,&quot;monitor&quot;:1}', ip: '192.168.0.51' },
    { id: 2, t: 'Today 12:02', who: 'KUET Admin', act: 'pc.isolate', target: 'PC-04', sum: 'Cut off network: local AI model found', json: '{&quot;reason&quot;:&quot;proc.ollama&quot;}', ip: '192.168.0.51' },
    { id: 3, t: 'Today 11:58', who: 'KUET Admin', act: 'screen.snapshot', target: 'Rupom2', sum: 'Took a snapshot', json: '{&quot;pc&quot;:&quot;Rupom2&quot;}', ip: '192.168.0.51' },
    { id: 4, t: 'Today 11:19', who: 'Course Instructor', act: 'session.start', target: 'CSER', sum: 'Started an Exam session for 90 minutes', json: '{&quot;profile&quot;:&quot;Exam: strict&quot;,&quot;minutes&quot;:90}', ip: '192.168.0.10' },
    { id: 5, t: 'Today 09:14', who: 'KUET Admin', act: 'signatures.publish', target: '2026.11.08-b2a25a', sum: 'Published rules to all PCs', json: '{&quot;note&quot;:&quot;Added Grok and LM Studio rules&quot;}', ip: '192.168.0.51' },
    { id: 6, t: 'Yesterday 15:40', who: 'Lab Assistant', act: 'enroll.approve', target: 'PC-15', sum: 'Approved a new PC', json: '{&quot;host&quot;:&quot;LAB-PC15&quot;,&quot;ip&quot;:&quot;192.168.0.115&quot;}', ip: '192.168.0.15' }
  ],
  get shown() { const q = this.q.toLowerCase(); return this.rows.filter(r => (!this.fam || r.act.startsWith(this.fam)) && (!q || (r.who + r.act + r.target + r.sum).toLowerCase().includes(q))); }
}"><div class="optbar"><span class="otitle">Audit log</span><span class="osub">A permanent record of staff actions. Entries can’t be edited or deleted.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="toolbar"><div class="pills">
    <button class="pill" :aria-pressed="fam === ''" @click="fam = ''">Everything</button><button class="pill" :aria-pressed="fam === 'screen.'" @click="fam = 'screen.'">Screen views</button><button class="pill" :aria-pressed="fam === 'pc.'" @click="fam = 'pc.'">PC actions</button><button class="pill" :aria-pressed="fam === 'session.'" @click="fam = 'session.'">Sessions</button><button class="pill" :aria-pressed="fam === 'signatures.'" @click="fam = 'signatures.'">Rules</button><button class="pill" :aria-pressed="fam === 'enroll.'" @click="fam = 'enroll.'">Enrolment</button></div>
    <span class="grow"></span><input class="input input-sm" style="width:240px" placeholder="Search person, action or PC" x-model="q"></div>
  <ul class="log">
    <template x-for="r in shown" :key="r.id"><li @click="openId = openId === r.id ? null : r.id" style="cursor:pointer">
      <span class="muted small" x-text="r.t"></span><span x-text="r.who"></span>
      <div><div x-text="r.sum" style="font-weight:500"></div><div class="small muted"><span class="mono" x-text="r.act"></span> · <span x-text="r.target"></span></div><code class="json" x-show="openId === r.id" x-html="r.json"></code></div>
      <span class="mono small muted" x-text="r.ip"></span></li></template>
  </ul>
  <div class="empty-state" x-show="!shown.length"><b>No entries</b>Nothing matches this filter.</div>
</div></div>
@endsection
