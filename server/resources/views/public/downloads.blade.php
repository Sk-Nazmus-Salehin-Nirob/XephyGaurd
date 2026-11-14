@extends('layouts.app', ['activePage' => ''])
@section('title', 'Downloads')
@section('content')
<div class="doc"><div class="optbar"><span class="otitle">Downloads</span><span class="osub">Everything needed to pair a lab PC with this server.</span><span class="grow"></span></div><div class="canvas ">
<section class="panel">
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-live"/></svg></span><div class="grow"><b>Windows installer</b><div class="muted small">XephyGuard-Setup.exe · 45 MB · Windows 10 and 11</div></div><button class="btn btn-solid" onclick="Alpine.store('toasts').add('Installer is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</button></div>
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-terminal"/></svg></span><div class="grow"><b>Ubuntu and Debian installer</b><div class="muted small">linux.sh · installs the agent as a service · Xorg sessions for screen view</div></div><button class="btn" onclick="Alpine.store('toasts').add('Script is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</button></div>
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-key"/></svg></span><div class="grow"><b>Lab certificate</b><div class="muted small">ca.crt · lets the lab hide AI summaries in search results</div></div><button class="btn" onclick="Alpine.store('toasts').add('Certificate is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</button></div>
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-globe"/></svg></span><div class="grow"><b>Proxy configuration</b><div class="muted small">proxy.pac · for labs that use proxy-only mode</div></div><button class="btn" onclick="Alpine.store('toasts').add('File is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</button></div>
</section>
<div class="cols-2">
  <section class="panel panel-pad stack" x-data="{ win: 'XephyGuard-Setup.exe /S /KEY=XG-A77CFB-6554C8-489B53 /CCC=http://192.168.0.51:8000', lin: 'curl -fsSL http://192.168.0.51:8000/install/linux.sh | sudo bash -s -- --key XG-A77CFB-6554C8-489B53' }">
    <h2 class="h2">Silent install</h2>
    <div><div class="cmd-label">Windows (as administrator)</div><div class="cmd"><pre x-text="win"></pre><button class="btn btn-sm copy" @click="xgCopy(win, 'Copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div></div>
    <div><div class="cmd-label">Ubuntu / Debian</div><div class="cmd"><pre x-text="lin"></pre><button class="btn btn-sm copy" @click="xgCopy(lin, 'Copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div></div>
  </section>
  <section class="panel panel-pad stack"><h2 class="h2">After installing</h2>
    <ol class="steps-num"><li><b>The agent starts by itself</b><div class="muted small">It runs in the background.</div></li><li><b>Approve it here</b><div class="muted small">It appears on <a href="enroll.html">Add a PC</a> within a few seconds.</div></li><li><b>If someone ends it</b><div class="muted small">The PC shows as offline on the map and an alert is raised.</div></li></ol></section>
</div></div></div>
@endsection
