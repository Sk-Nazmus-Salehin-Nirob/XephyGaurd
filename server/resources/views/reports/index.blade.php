@extends('layouts.app', ['activePage' => 'reports.html'])
@section('title', 'Reports')
@section('content')
@php
  $defaultTo = now()->format('Y-m-d');
  $defaultFrom = now()->subDays(30)->format('Y-m-d');
@endphp
<div class="doc" x-data="{ from: '{{ $defaultFrom }}', to: '{{ $defaultTo }}' }"><div class="optbar"><span class="otitle">Reports</span><span class="osub">Every session is scored once it ends. A person decides what it means.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="cols-main">
    <section>
      @if(!empty($sessions) && $sessions->count())
        @foreach($sessions as $s)
          @php
            $rep = isset($reports) ? ($reports[$s->id] ?? null) : null;
            $flagged = (int) ($rep?->summary['flagged'] ?? 0);
            $pcCount = (int) ($rep?->summary['pcs'] ?? ($s->session_pcs_count ?? 0));
          @endphp
          <div class="rep">
            <div class="datebox"><b>{{ ($s->ended_at ?? $s->starts_at)?->format('d') ?? '—' }}</b><span>{{ ($s->ended_at ?? $s->starts_at)?->format('M') ?? '' }}</span></div>
            <div>
              <div style="font-weight:600">{{ $s->course }}</div>
              <div class="small muted" style="margin-top:2px">{{ $s->starts_at?->format('H:i') ?? '—' }} · {{ ucfirst(str_replace('_', ' ', $s->mode)) }}{{ $pcCount ? ' · ' . $pcCount . ' PCs' : '' }}</div>
            </div>
            @if($flagged > 0)
              <span class="chip alert"><span class="dot alert"></span>{{ $flagged }} flagged</span>
            @else
              <span class="chip ok"><span class="dot ok"></span>No flags</span>
            @endif
            <div class="row">
              <a class="btn btn-sm btn-solid" href="{{ route('reports.show', $s) }}">Open</a>
              <a class="btn btn-sm" href="{{ route('reports.pdf', $s) }}">PDF</a>
              <a class="btn btn-sm" href="{{ route('reports.csv', $s) }}">CSV</a>
            </div>
          </div>
        @endforeach
      @else
        <div class="panel empty-state"><b>No completed sessions yet</b>Reports appear here automatically once a session ends.</div>
      @endif
    </section>
    <form method="get" action="{{ route('research.export') }}" class="panel panel-pad stack">
      <div><h2 class="h2">Research export</h2><p class="muted small" style="margin-top:2px">Pseudonymised data for students who gave consent. Names never leave this server.</p></div>
      <label class="field"><span>From</span><input name="from" class="input" type="date" x-model="from"></label>
      <label class="field"><span>Until</span><input name="until" class="input" type="date" x-model="to"></label>
      <button type="submit" class="btn btn-solid"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Export CSV</button>
    </form>
  </div>
</div></div>
@endsection
