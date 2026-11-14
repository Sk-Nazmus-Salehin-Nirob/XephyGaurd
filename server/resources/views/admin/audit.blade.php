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
  })->values()->all() : [];
@endphp
<script>
window.XG_AUDIT_PAGE = {
  rows: @json($liveAudit),
};
</script>
<div class="doc" x-data="{
  fam: '', q: '', openId: null,
  rows: window.XG_AUDIT_PAGE.rows || [],
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
