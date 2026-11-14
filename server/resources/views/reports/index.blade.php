@extends('layouts.app', ['activePage' => 'reports.html'])
@section('title', 'Reports')
@section('content')
<div class="doc" x-data="{ from: '2026-10-01', to: '2026-11-08' }"><div class="optbar"><span class="otitle">Reports</span><span class="osub">Every session is scored once it ends. A person decides what it means.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="cols-main">
    <section>
      <div class="rep"><div class="datebox"><b>07</b><span>Nov</span></div><div><div style="font-weight:600">CSE 1101 practice</div><div class="small muted" style="margin-top:2px">14:00 · Practice · 15 PCs</div></div><span class="chip ok"><span class="dot ok"></span>No flags</span><div class="row"><a class="btn btn-sm btn-solid" href="report-session-2.html">Open</a><button class="btn btn-sm" onclick="window.print()">PDF</button><button class="btn btn-sm" onclick="Alpine.store('toasts').add('CSV is downloading.', 'info')">CSV</button></div></div>
      <div class="rep"><div class="datebox"><b>05</b><span>Nov</span></div><div><div style="font-weight:600">CSE 3201 quiz</div><div class="small muted" style="margin-top:2px">09:30 · Test · 15 PCs</div></div><span class="chip alert"><span class="dot alert"></span>2 flagged</span><div class="row"><a class="btn btn-sm btn-solid" href="report-session-1.html">Open</a><button class="btn btn-sm" onclick="window.print()">PDF</button><button class="btn btn-sm" onclick="Alpine.store('toasts').add('CSV is downloading.', 'info')">CSV</button></div></div>
      <div class="rep"><div class="datebox"><b>03</b><span>Nov</span></div><div><div style="font-weight:600">CSE 2200 project lab</div><div class="small muted" style="margin-top:2px">10:00 · Always-on · 12 PCs</div></div><span class="chip watch"><span class="dot watch"></span>1 flagged</span><div class="row"><a class="btn btn-sm btn-solid" href="report-session-1.html">Open</a><button class="btn btn-sm" onclick="window.print()">PDF</button><button class="btn btn-sm" onclick="Alpine.store('toasts').add('CSV is downloading.', 'info')">CSV</button></div></div>
    </section>
    <aside class="panel panel-pad stack">
      <div><h2 class="h2">Research export</h2><p class="muted small" style="margin-top:2px">Pseudonymised data for students who gave consent. Names never leave this server.</p></div>
      <label class="field"><span>From</span><input class="input" type="date" x-model="from"></label>
      <label class="field"><span>Until</span><input class="input" type="date" x-model="to"></label>
      <button class="btn btn-solid" @click="$store.toasts.add('Research CSV is being prepared.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Export CSV</button>
    </aside>
  </div>
</div></div>
@endsection
