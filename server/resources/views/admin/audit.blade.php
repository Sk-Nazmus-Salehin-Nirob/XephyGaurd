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
          'json' => json_encode($e->details ?? [], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES),
          'ip' => $e->ip ?? '—',
      ];
  })->values()->all() : [];
@endphp
<script type="application/json" id="xg-page-data">{!! json_encode([
  'rows' => $liveAudit,
  'fam' => request()->string('action')->toString(),
  'total' => isset($entries) ? $entries->total() : count($liveAudit),
  'hasPages' => isset($entries) && $entries->hasPages(),
], JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) !!}</script>
<div class="doc" x-data="auditPage"><div class="optbar"><span class="otitle">Audit log</span><span class="osub">A permanent record of staff actions. Entries can’t be edited or deleted.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="toolbar"><div class="pills">
    <button class="pill" :aria-pressed="fam === ''" @click="setFam('')">Everything</button><button class="pill" :aria-pressed="fam === 'screen.'" @click="setFam('screen.')">Screen views</button><button class="pill" :aria-pressed="fam === 'pc.'" @click="setFam('pc.')">PC actions</button><button class="pill" :aria-pressed="fam === 'session.'" @click="setFam('session.')">Sessions</button><button class="pill" :aria-pressed="fam === 'signatures.'" @click="setFam('signatures.')">Rules</button><button class="pill" :aria-pressed="fam === 'enroll.'" @click="setFam('enroll.')">Enrolment</button></div>
    <span class="grow"></span><input class="input input-sm" style="width:240px" placeholder="Search person, action or PC" x-model="q"></div>
  <ul class="log">
    <template x-for="r in shown" :key="r.id"><li @click="openId = openId === r.id ? null : r.id" style="cursor:pointer">
      <span class="muted small" x-text="r.t"></span><span x-text="r.who"></span>
      <div><div x-text="r.sum" style="font-weight:500"></div><div class="small muted"><span class="mono" x-text="r.act"></span> · <span x-text="r.target"></span></div><code class="json" x-show="openId === r.id" x-text="r.json"></code></div>
      <span class="mono small muted" x-text="r.ip"></span></li></template>
  </ul>
  <div class="empty-state" x-show="!shown.length"><b>No entries</b>Nothing matches this filter.</div>
  @if(isset($entries) && $entries->total() > 0)
  <div class="panel" style="margin-top:12px">
    <div class="tbl-foot">
      <span>Showing {{ $entries->firstItem() }}–{{ $entries->lastItem() }} of {{ $entries->total() }} entries</span>
      @if($entries->hasPages())
        <div class="pager">
          @if($entries->onFirstPage())
            <button disabled>Prev</button>
          @else
            <a class="btn btn-sm" href="{{ $entries->previousPageUrl() }}">Prev</a>
          @endif
          @if($entries->hasMorePages())
            <a class="btn btn-sm" href="{{ $entries->nextPageUrl() }}">Next</a>
          @else
            <button disabled>Next</button>
          @endif
        </div>
      @endif
    </div>
  </div>
  @endif
</div></div>
@endsection
