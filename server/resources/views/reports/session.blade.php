@extends('layouts.app', ['activePage' => 'reports.html'])
@section('title', 'Session report')
@section('content')
@if(!empty($session))
<div class="doc"><div class="optbar noprint">
  @if(!empty($student))
    <a class="btn btn-quiet btn-sm" href="{{ route('reports.show', $session) }}"><svg class="i i-sm" aria-hidden="true"><use href="#i-back"/></svg> Session report</a>
  @else
    <a class="btn btn-quiet btn-sm" href="{{ route('reports.index') }}"><svg class="i i-sm" aria-hidden="true"><use href="#i-back"/></svg> Reports</a>
  @endif
  <span class="otitle">{{ !empty($student) ? 'Student report · ' . $student->name : 'Session report' }}</span>
  <span class="osub">{{ $session->course }} · {{ ($session->starts_at ?? now())->format('j F Y') }}</span>
  <span class="grow"></span>
  <form method="post" action="{{ route('reports.rescore', $session) }}" style="display:inline">
    @csrf
    <button type="submit" class="btn btn-sm"><svg class="i i-sm" aria-hidden="true"><use href="#i-refresh"/></svg> Re-score</button>
  </form>
  <a class="btn btn-sm" href="{{ route('reports.csv', $session) }}"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> CSV</a>
  <a class="btn btn-sm" href="{{ route('reports.pdf', $session) }}"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> PDF</a>
  <button class="btn btn-sm btn-solid" onclick="window.print()"><svg class="i i-sm" aria-hidden="true"><use href="#i-print"/></svg> Print or save as PDF</button>
</div>
<div class="canvas pad"><article class="paper">
  <div class="row" style="--gap:10px;margin-bottom:12px"><span class="mode {{ $session->mode }}">{{ ucfirst(str_replace('_', ' ', $session->mode)) }}</span><span class="muted small">Academic integrity report</span></div>
  <h1>{{ $session->course }}{{ !empty($student) ? ' · ' . $student->name . ' (' . $student->student_number . ')' : '' }}</h1>
  <p class="meta">{{ ($session->starts_at ?? now())->format('j F Y · H:i') }}{{ $session->ended_at ? ' – ' . $session->ended_at->format('H:i') : '' }} · Profile “{{ $session->profile?->name ?? ucfirst($session->mode) }}” · {{ isset($scores) ? $scores->count() : 0 }} scores</p>
  <p class="disclaimer"><b>Read this first.</b> Scores summarise signals the system could observe. They are not proof of anything, and some things cannot be observed at all. A flag is a reason to talk to the student.</p>
  <h2>1. Scores</h2>
  <table class="tbl"><thead><tr><th>PC</th><th>Student</th><th>Method</th><th>Score</th><th>Confidence</th><th>What was observed</th></tr></thead><tbody>
    @forelse($scores ?? [] as $s)
      @php
        $integrity = max(0, min(100, 100 - (int) $s->score));
        $barClass = $integrity < 70 ? 'low' : ($integrity < 90 ? 'mid' : '');
        $reasons = is_array($s->reasons) ? $s->reasons : [];
      @endphp
      <tr>
        <td class="name">{{ $s->pc?->name ?? ('PC-' . $s->pc_id) }}</td>
        <td class="mono">
          @if($s->student)
            <a href="{{ route('reports.student', [$session, $s->student]) }}">{{ $s->student->name }} ({{ $s->user ?: $s->student->login }})</a>
          @else
            {{ $s->user ?: '—' }}
          @endif
        </td>
        <td class="muted small">{{ $s->method }}</td>
        <td><div class="scorebar {{ $barClass }}"><i><b style="width:{{ $integrity }}%"></b></i><span>{{ $integrity }}/100</span></div></td>
        <td>{{ ucfirst($s->confidence ?? 'Medium') }}</td>
        <td>
          @if(count($reasons))
            <div class="signals">
              @foreach($reasons as $r)
                <span><b>+{{ $r['points'] ?? $r['weight'] ?? 5 }}</b>{{ $r['label'] ?? $r['reason'] ?? '' }}</span>
              @endforeach
            </div>
          @else
            <span class="muted">Normal activity</span>
          @endif
        </td>
      </tr>
    @empty
      <tr><td colspan="6" class="muted">No scores recorded yet. Use Re-score to compute session scores.</td></tr>
    @endforelse
  </tbody></table>
  <p class="small muted" style="margin-top:8px">Lowest integrity scores first. The CSV has every PC.</p>
  <h2>2. Alerts ({{ isset($alerts) ? $alerts->count() : 0 }})</h2>
  <table class="tbl"><thead><tr><th>Time</th><th>PC</th><th>Severity</th><th>What happened</th><th>Review</th></tr></thead><tbody>
    @forelse($alerts ?? [] as $a)
      <tr>
        <td class="mono">{{ $a->occurred_at?->format('H:i') }}</td>
        <td class="name">{{ $a->pc?->name ?? ('PC-' . $a->pc_id) }}</td>
        <td><span class="sev {{ $a->severity }}">{{ $a->severity }}</span></td>
        <td>{{ $a->title ?: $a->rule_id }}</td>
        <td>{{ $a->acknowledged_at ? 'Reviewed' : 'Open' }}</td>
      </tr>
    @empty
      <tr><td colspan="5" class="muted">No alerts raised during this session.</td></tr>
    @endforelse
  </tbody></table>
  @if(!empty($blocked) && $blocked->count())
  <h2>3. Blocked connections ({{ $blocked->count() }})</h2>
  <table class="tbl"><thead><tr><th>PC</th><th>Host</th><th>Category</th><th class="right">Attempts</th><th>First seen</th></tr></thead><tbody>
    @foreach($blocked as $b)
      <tr>
        <td class="name">{{ $b->pc?->name ?? ('PC-' . $b->pc_id) }}</td>
        <td class="mono">{{ $b->host }}</td>
        <td>{{ $b->category }}</td>
        <td class="right num">{{ $b->n }}</td>
        <td class="mono muted">{{ \Illuminate\Support\Carbon::parse($b->first_at)->format('H:i:s') }}</td>
      </tr>
    @endforeach
  </tbody></table>
  @endif
  @if(!empty($pastes) && $pastes->count())
  <h2>Large pastes ({{ $pastes->count() }})</h2>
  <table class="tbl"><thead><tr><th>Time</th><th>Size</th><th>From</th><th>Into</th></tr></thead><tbody>
    @foreach($pastes as $p)
      <tr>
        <td class="mono">{{ $p->occurred_at?->format('H:i:s') }}</td>
        <td>{{ $p->chars }} characters, {{ $p->lines }} lines</td>
        <td>{{ $p->source_app ?: '—' }}</td>
        <td>{{ $p->target_app ?: '—' }}</td>
      </tr>
    @endforeach
  </tbody></table>
  @endif
  <h2>What could not be observed</h2>
  <p style="color:#46505c">Phones and other devices, notes on paper, and anything said between students. Screen snapshots are taken only when an instructor asks for one.</p>
  <p class="paper-foot">Generated by XephyGuard. Keystrokes, clipboard text and passwords are never recorded.</p>
</article></div></div>
@else
<div class="doc"><div class="optbar noprint"><a class="btn btn-quiet btn-sm" href="reports.html"><svg class="i i-sm" aria-hidden="true"><use href="#i-back"/></svg> Reports</a><span class="otitle">Session report</span><span class="osub">CSE 3201 · 5 November 2026</span><span class="grow"></span>
  <button class="btn btn-sm" onclick="Alpine.store('toasts').add('Scores are being recalculated…', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-refresh"/></svg> Re-score</button>
  <button class="btn btn-sm" onclick="Alpine.store('toasts').add('CSV is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> CSV</button>
  <button class="btn btn-sm btn-solid" onclick="window.print()"><svg class="i i-sm" aria-hidden="true"><use href="#i-print"/></svg> Print or save as PDF</button></div>
<div class="canvas pad"><article class="paper">
  <div class="row" style="--gap:10px;margin-bottom:12px"><span class="mode test">Test</span><span class="muted small">Academic integrity report</span></div>
  <h1>CSE 3201 · Operating Systems quiz</h1><p class="meta">5 November 2026 · 09:30 – 12:30 · Profile “Test: AI blocked” · 15 PCs</p>
  <p class="disclaimer"><b>Read this first.</b> Scores summarise signals the system could observe. They are not proof of anything, and some things cannot be observed at all. A flag is a reason to talk to the student.</p>
  <h2>1. Scores</h2>
  <table class="tbl"><thead><tr><th>PC</th><th>Student</th><th>Score</th><th>Confidence</th><th>What was observed</th></tr></thead><tbody>
    <tr><td class="name">Rupom2</td><td class="mono">std_210701</td><td><div class="scorebar low"><i><b style="width:60%"></b></i><span>60/100</span></div></td><td>Medium</td>
          <td><div class="signals"><span><b>+25</b>AI service seen: Grok (xAI), 12 requests</span><span><b>+10</b>Session helper was ended, twice</span><span><b>+5</b>USB device attached</span></div></td></tr>
        <tr><td class="name">PC-09</td><td class="mono">std_210719</td><td><div class="scorebar mid"><i><b style="width:82%"></b></i><span>82/100</span></div></td><td>Low</td><td><div class="signals"><span><b>+18</b>Large paste, 412 characters</span></div></td></tr>
        <tr><td class="name">SIyam</td><td class="mono">std_210712</td><td><div class="scorebar"><i><b style="width:98%"></b></i><span>98/100</span></div></td><td>High</td><td class="muted">Normal coding rhythm</td></tr>
        <tr><td class="name">PC-07</td><td class="mono">std_210717</td><td><div class="scorebar"><i><b style="width:100%"></b></i><span>100/100</span></div></td><td>High</td><td class="muted">Normal activity</td></tr>
  </tbody></table>
  <p class="small muted" style="margin-top:8px">Lowest scores first. The CSV has every PC.</p>
  <h2>2. Alerts (3)</h2>
  <table class="tbl"><thead><tr><th>Time</th><th>PC</th><th>Severity</th><th>What happened</th><th>Review</th></tr></thead><tbody>
    <tr><td class="mono">09:52</td><td class="name">Rupom2</td><td><span class="sev high">high</span></td><td>Grok (xAI) stream: chrome to cdn.grok.com <span class="muted">×3</span></td><td>Reviewed</td></tr>
        <tr><td class="mono">09:41</td><td class="name">Rupom2</td><td><span class="sev high">high</span></td><td>Session helper was terminated <span class="muted">×2</span></td><td>Reviewed</td></tr>
        <tr><td class="mono">09:38</td><td class="name">PC-09</td><td><span class="sev low">low</span></td><td>Large paste: 412 characters</td><td>Reviewed</td></tr>
  </tbody></table>
  <h2>3. What could not be observed</h2>
  <p style="color:#46505c">Phones and other devices, notes on paper, and anything said between students. Screen snapshots are taken only when an instructor asks for one.</p>
  <p class="paper-foot">Generated by XephyGuard. Keystrokes, clipboard text and passwords are never recorded.</p>
</article></div></div>
@endif
@endsection
