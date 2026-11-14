@extends('layouts.app', ['activePage' => 'health.html'])
@section('title', 'Health')
@section('content')
@php
  $liveChecks = collect($checks ?? []);
  $okCount = $liveChecks->where('ok', true)->count();
  $totalCount = $liveChecks->count();
  $hasDisk = isset($disk['free'], $disk['total']) && $disk['total'] > 0;
  $freeGb = $hasDisk ? round($disk['free'] / 1073741824, 1) : 0;
  $totalGb = $hasDisk ? round($disk['total'] / 1073741824, 1) : 0;
  $usedPct = $hasDisk ? min(100, max(1, (int) round((($totalGb - $freeGb) / $totalGb) * 100))) : 0;
@endphp
<div class="doc" x-data="healthPage"><div class="optbar"><span class="otitle">Health</span><span class="osub"><b>{{ $okCount }} of {{ $totalCount }}</b> checks passed. CLI: <code class="mono">sudo xephyguard-ccc doctor</code></span><span class="grow"></span><button class="btn btn-solid" @click="rerun()" :disabled="running"><svg class="i i-sm" :class="running && 'spin'"><use href="#i-refresh"/></svg> <span x-text="running ? 'Checking…' : 'Run checks again'"></span></button></div><div class="canvas ">
  
  <div class="cols-main">
    <section class="panel"><ul class="checks">
      @forelse($liveChecks as $c)
        <li>
          <span class="{{ $c['ok'] ? 'tick-ok' : 'tick-warn' }}"><svg class="i i-sm" aria-hidden="true"><use href="#{{ $c['ok'] ? 'i-check' : 'i-warn' }}"/></svg></span>
          <div>
            <b>{{ $c['name'] ?? $c['label'] ?? 'Check' }}</b>
            <div class="small muted">{{ $c['detail'] ?? $c['message'] ?? '' }}</div>
          </div>
        </li>
      @empty
        <li class="muted small" style="padding:18px 20px">No health check results returned.</li>
      @endforelse
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
          <p class="small muted">No agent versions reported yet.</p>
        @endif
      </section>
      <section class="panel panel-pad stack"><h2 class="h2">Storage</h2>
        @if($hasDisk)
          <div class="meter"><i style="width:{{ $usedPct }}%"></i></div><p class="small"><b>{{ $freeGb }} GB</b> free of {{ $totalGb }} GB</p>
        @else
          <p class="small muted">Disk telemetry unavailable.</p>
        @endif
      </section>
      <section class="panel">
        <div class="panel-head"><h2 class="h2">PCs needing attention</h2></div>
        @if(!empty($attention) && $attention->count())
          <ul class="cmdlog" style="padding:4px 20px 8px">
            @foreach($attention as $p)
              <li>
                <span class="dot {{ $p->online() ? 'watch' : 'off' }}"></span>
                <span class="grow"><b>{{ $p->name }}</b> · {{ !$p->online() ? 'Offline' : ($p->isolated ? 'Isolated' : (($p->usage['helpers'] ?? 1) === 0 ? 'Session helper stopped' : 'Reduced capabilities')) }}</span>
                <a class="small" href="{{ route('dashboard') }}#pc={{ $p->id }}">Inspect</a>
              </li>
            @endforeach
          </ul>
        @else
          <div class="panel-body small muted">All enrolled PCs look healthy.</div>
        @endif
      </section>
    </div>
  </div>
</div></div>
@endsection
