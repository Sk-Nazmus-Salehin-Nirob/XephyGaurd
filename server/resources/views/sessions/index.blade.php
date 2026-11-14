@extends('layouts.app', ['activePage' => 'sessions.html'])
@section('title', 'Sessions')
@section('content')
<div class="doc" x-data="{ startOpen: location.hash === '#start', bc: '' }"><div class="optbar"><span class="otitle">Sessions</span><span class="osub">Start, watch and review lab sessions.</span><span class="grow"></span><button class="btn btn-solid" @click="startOpen = true"><svg class="i i-sm" aria-hidden="true"><use href="#i-plus"/></svg> Start a session</button></div><div class="canvas ">
  

  <section class="nowhero">
    <div class="row" style="align-items:flex-start;--gap:12px">
      <div class="grow">
        <div class="row" style="--gap:8px;margin-bottom:8px"><span class="mode exam">Exam</span><span class="chip ok"><span class="dot ok"></span>Running</span></div>
        <div class="title">CSER · Software engineering lab exam</div>
        <p class="muted" style="margin-top:4px">Exam: strict · started 11:19 · 90 minutes · 15 PCs</p>
      </div>
      <button class="btn btn-danger" onclick="if(confirm('End the session? Restrictions lift immediately.')) Alpine.store('toasts').add('Session ended.', 'watch')">End session</button>
    </div>
    <div class="clock" aria-label="41 minutes remaining">
      <span class="tick" style="left:54%">12:08</span>
      <div class="track"><i style="width:54%"></i></div>
      <div class="ends"><span>11:19</span><span>41 min left</span><span>12:49</span></div>
    </div>
  </section>

  <div class="cols-main">
    <div>
      <section class="panel">
        <div class="panel-head"><h2 class="h2">Per-PC rules</h2><span class="chip plain">Changes are audited</span></div>
        <div class="table-wrap"><table class="tbl">
          <thead><tr><th>PC</th><th>Rules</th><th>Reason</th><th></th></tr></thead>
          <tbody>
            <tr><td class="name">SIyam</td><td><select class="select select-sm" style="width:200px"><option>Same as session</option><option selected>Practice: AI allowed</option><option>Exam: strict</option></select></td><td><input class="input input-sm" value="Screen reader and speech tools"></td><td class="right"><button class="btn btn-sm" onclick="Alpine.store('toasts').add('Saved for SIyam.', 'ok')">Save</button></td></tr>
            <tr><td class="name">PC-08</td><td><select class="select select-sm" style="width:200px"><option selected>Same as session</option><option>Practice: AI allowed</option><option>Exam: strict</option></select></td><td><input class="input input-sm" placeholder="Why does this PC differ?"></td><td class="right"><button class="btn btn-sm" onclick="Alpine.store('toasts').add('Saved for PC-08.', 'ok')">Save</button></td></tr>
          </tbody></table></div>
      </section>
      <section class="panel">
        <div class="panel-head"><h2 class="h2">Past sessions</h2><a class="small" href="reports.html">All reports</a></div>
        <div class="table-wrap"><table class="tbl">
          <thead><tr><th>When</th><th>Course</th><th>Profile</th><th></th></tr></thead>
          <tbody>
            <tr><td class="nw">Today 11:19 – now</td><td class="name">CSER lab exam</td><td><span class="mode exam">Exam</span></td><td class="right"><span class="chip ok">Running</span></td></tr>
            <tr><td class="nw">Nov 07 · 14:00 – 16:00</td><td class="name">CSE 1101 practice</td><td><span class="mode practice">Practice</span></td><td class="right"><a href="report-session-2.html">View report</a></td></tr>
            <tr><td class="nw">Nov 05 · 09:30 – 12:30</td><td class="name">CSE 3201 quiz</td><td><span class="mode test">Test</span></td><td class="right"><a href="report-session-1.html">View report</a></td></tr>
          </tbody></table></div>
        <div class="tbl-foot">3 of 18 sessions <div class="pager"><button aria-current="page">1</button><button>2</button></div></div>
      </section>
    </div>
    <div>
      <section class="panel panel-pad stack">
        <div><h2 class="h2">Broadcast a message</h2><p class="muted small" style="margin-top:2px">Appears on every connected student screen.</p></div>
        <textarea class="textarea" rows="3" placeholder="e.g. 10 minutes left. Please commit your code." x-model="bc"></textarea>
        <div class="pills"><button class="pill" @click="bc = '10 minutes left. Please commit your code.'">10 minute warning</button><button class="pill" @click="bc = 'Please close other browser tabs.'">Close tabs</button></div>
        <button class="btn btn-solid" @click="if(bc.trim()) { $store.toasts.add('Sent to all 14 online PCs.', 'ok'); bc = '' }"><svg class="i i-sm" aria-hidden="true"><use href="#i-send"/></svg> Send to all PCs</button>
      </section>
      <section class="panel">
        <div class="panel-head"><h2 class="h2">Recent commands</h2></div>
        <ul class="cmdlog" style="padding:4px 20px 8px">
          <li><span class="mono muted small">12:02</span><span><b>PC-04</b> cut off network</span><span class="chip ok">Done</span></li>
          <li><span class="mono muted small">11:58</span><span><b>Rupom2</b> snapshot</span><span class="chip ok">Done</span></li>
          <li><span class="mono muted small">11:41</span><span><b>PC-09</b> rescan</span><span class="chip ok">Done</span></li>
          <li><span class="mono muted small">11:19</span><span><b>All PCs</b> apply Exam profile</span><span class="chip ok">Done</span></li>
        </ul>
      </section>
    </div>
  </div>

  <div class="overlay" x-show="startOpen" x-cloak x-transition.opacity @click.self="startOpen = false" @keydown.escape.window="startOpen = false">
    <div class="modal" style="width:min(520px,100%)" role="dialog" aria-label="Start a session">
      <div class="modal-head"><span class="h2">Start a session</span><button class="xbtn" @click="startOpen = false" aria-label="Close"><svg class="i" aria-hidden="true"><use href="#i-x"/></svg></button></div>
      <form onsubmit="event.preventDefault(); Alpine.store('toasts').add('Session scheduled.', 'ok')">
        <div class="modal-body stack">
          <label class="field"><span>Course</span><input class="input" placeholder="e.g. CSE 3100" required></label>
          <div class="form-grid">
            <label class="field"><span>Policy profile</span><select class="select"><option>Exam: strict</option><option>Test: AI blocked</option><option>Practice: AI allowed</option><option>Practice: AI blocked</option><option>Always-on</option></select></label>
            <label class="field"><span>Duration (minutes)</span><input class="input" type="number" min="10" placeholder="90"></label>
          </div>
          <label class="field"><span>Research condition</span><select class="select"><option value="">None</option><option>Baseline</option><option>Treatment</option></select></label>
        </div>
        <div class="modal-foot"><button type="button" class="btn" @click="startOpen = false">Cancel</button><button class="btn btn-solid">Start session</button></div>
      </form>
    </div>
  </div>
</div></div>
@endsection
