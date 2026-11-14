@extends('layouts.app', ['activePage' => 'health.html'])
@section('title', 'Health')
@section('content')
<div class="doc" x-data="{ running: false, rerun() { this.running = true; setTimeout(() => { this.running = false; $store.toasts.add('Checks finished: 11 passed, 1 needs a look.', 'info'); }, 1100); } }"><div class="optbar"><span class="otitle">Health</span><span class="osub"><b>11 of 12</b> checks passed.</span><span class="grow"></span><button class="btn btn-solid" @click="rerun()" :disabled="running"><svg class="i i-sm" :class="running && 'spin'"><use href="#i-refresh"/></svg> <span x-text="running ? 'Checking…' : 'Run checks again'"></span></button></div><div class="canvas ">
  
  <div class="cols-main">
    <section class="panel"><ul class="checks">
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
    </ul></section>
    <div>
      <section class="panel panel-pad stack"><h2 class="h2">Agent versions</h2>
        <div><div class="row" style="justify-content:space-between"><span class="mono small">v1.4.2 <span class="muted">latest</span></span><b>14 PCs</b></div><div class="meter" style="margin-top:6px"><i style="width:93%"></i></div></div>
        <div><div class="row" style="justify-content:space-between"><span class="mono small">v1.4.0</span><b>1 PC</b></div><div class="meter" style="margin-top:6px"><i style="width:7%;background:var(--watch)"></i></div></div></section>
      <section class="panel panel-pad stack"><h2 class="h2">Storage</h2><div class="meter"><i style="width:28%"></i></div><p class="small"><b>142 GB</b> free of 512 GB</p></section>
    </div>
  </div>
</div></div>
@endsection