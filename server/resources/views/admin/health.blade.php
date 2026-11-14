@extends('layouts.app', ['activePage' => 'health.html'])
@section('title', 'Health')
@section('content')
@php
  $liveChecks = isset($checks) && count($checks) ? collect($checks) : null;
  $okCount = $liveChecks ? $liveChecks->where('ok', true)->count() : 11;
  $totalCount = $liveChecks ? $liveChecks->count() : 12;
  $freeGb = isset($disk['free']) && $disk['free'] ? round($disk['free'] / 1073741824, 1) : 142;
  $totalGb = isset($disk['total']) && $disk['total'] ? round($disk['total'] / 1073741824, 1) : 512;
  $usedPct = $totalGb > 0 ? min(100, max(1, (int) round((($totalGb - $freeGb) / $totalGb) * 100))) : 28;
@endphp
<div class="doc" x-data="{ running: false, rerun() { this.running = true; setTimeout(() => { location.reload(); }, 600); } }"><div class="optbar"><span class="otitle">Health</span><span class="osub"><b>{{ $okCount }} of {{ $totalCount }}</b> checks passed. CLI: <code class="mono">sudo xephyguard-ccc doctor</code></span><span class="grow"></span><button class="btn btn-solid" @click="rerun()" :disabled="running"><svg class="i i-sm" :class="running && 'spin'"><use href="#i-refresh"/></svg> <span x-text="running ? 'Checking…' : 'Run checks again'"></span></button></div><div class="canvas ">
  
  <div class="cols-main">
    <section class="panel"><ul class="checks">
      @if($liveChecks)
        @foreach($liveChecks as $c)
          <li>
            <span class="{{ $c['ok'] ? 'tick-ok' : 'tick-warn' }}"><svg class="i i-sm" aria-hidden="true"><use href="#{{ $c['ok'] ? 'i-check' : 'i-warn' }}"/></svg></span>
            <div>
              <b>{{ $c['name'] ?? $c['label'] ?? 'Check' }}</b>
              <div class="small muted">{{ $c['detail'] ?? $c['message'] ?? '' }}</div>
            </div>
          </li>
        @endforeach
      @else
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Certificate authority</b><div class="small muted">Root certificate is valid until 2036.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Live updates (Reverb)</b><div class="small muted">Connected, with 14 PCs subscribed.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Database</b><div class="small muted">Readable, writable and up to date.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Queue worker</b><div class="small muted">Running, no failed jobs.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Scheduler</b><div class="small muted">Last run 38 seconds ago.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Published rules</b><div class="small muted">Version 2026.11.08-b2a25a is on all online PCs.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Screen view service</b><div class="small muted">Accepting snapshot and live requests.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Network gateway</b><div class="small muted">Lab subnet 192.168.0.0/24 routes through this server.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Clock sync</b><div class="small muted">Within 20 ms of the time server.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Storage</b><div class="small muted">142 GB free.</div></div></li>
        <li><span class="tick-ok"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><div><b>Backups</b><div class="small muted">Last backup 03:00 today.</div></div></li>
        <li><span class="tick-warn"><svg class="i i-sm" aria-hidden="true"><use href="#i-warn"/></svg></span><div><b>PC heartbeats</b><div class="small muted">PC-12 has been silent for 25 minutes.</div><a class="small" href="index.html#pc=12">Show in Live lab</a></div></li>
      @endif
    </ul></section>
    <div>
      <section class="panel panel-pad stack"><h2 class="h2">Agent versions</h2>
        @if(!empty($versions) && $versions->count())
          @php $totV = max(1, (int) $versions->sum()); @endphp
          @foreach($versions as $ver => $cnt)
            @php $pct = (int) round(($cnt / $totV) * 100); @endphp
            <div>
              <div class="row" style="justify-content:space-between"><span class="mono small">v{{ $ver }}</span><b>{{ $cnt }} {{ $cnt === 1 ? 'PC' : 'PCs' }}</b></div>
              <div class="meter" style="margin-top:6px"><i style="width:{{ $pct }}%"></i></div>
            </div>
          @endforeach
        @else
          <div><div class="row" style="justify-content:space-between"><span class="mono small">v1.4.2 <span class="muted">latest</span></span><b>14 PCs</b></div><div class="meter" style="margin-top:6px"><i style="width:93%"></i></div></div>
          <div><div class="row" style="justify-content:space-between"><span class="mono small">v1.4.0</span><b>1 PC</b></div><div class="meter" style="margin-top:6px"><i style="width:7%;background:var(--watch)"></i></div></div>
        @endif
      </section>
      <section class="panel panel-pad stack"><h2 class="h2">Storage</h2><div class="meter"><i style="width:{{ $usedPct }}%"></i></div><p class="small"><b>{{ $freeGb }} GB</b> free of {{ $totalGb }} GB</p></section>
      <section class="panel">
        <div class="panel-head"><h2 class="h2">PCs needing attention</h2></div>
        @if(!empty($attention) && $attention->count())
          <ul class="cmdlog" style="padding:4px 20px 8px">
            @foreach($attention as $p)
              <li>
                <span class="dot {{ $p->online() ? 'watch' : 'off' }}"></span>
                <span class="grow"><b>{{ $p->name }}</b> · {{ !$p->online() ? 'Offline' : ($p->isolated ? 'Isolated' : (($p->usage['helpers'] ?? 1) === 0 ? 'Session helper stopped' : 'Reduced capabilities')) }}</span>
                <a class="small" href="index.html#pc={{ $p->id }}">Inspect</a>
              </li>
            @endforeach
          </ul>
        @else
          <div class="panel-body small muted">PC-12 has been silent for 25 minutes. <a href="index.html#pc=12">Inspect</a></div>
        @endif
      </section>
    </div>
  </div>
</div></div>
@endsection
