@extends('layouts.app', ['activePage' => ''])
@section('title', 'Downloads')
@section('content')
@php
  $cccHost = $ccc ?: request()->getHost();
  $portSuffix = request()->getPort() && !in_array(request()->getPort(), [80, 443], true) ? ':' . request()->getPort() : '';
  $baseUrl = (request()->isSecure() ? 'https://' : 'http://') . $cccHost . $portSuffix;
  $enrollKey = $key ?? '';
  $exeName = $setupFile ?? '';
  $exeMeta = $exeName ? collect($files ?? [])->firstWhere('name', $exeName) : null;
  $exeSize = $exeMeta ? ($exeMeta['size_mb'] . ' MB · ') : '';
  $winCmd = ($exeName ?: 'XephyGuard-Setup.exe') . ' /S /KEY=' . ($enrollKey ?: '<ROTATE_KEY_FIRST>') . ' /CCC=' . $baseUrl;
  $linCmd = 'curl -fsSL ' . $baseUrl . '/install/linux.sh | sudo bash -s -- --key ' . ($enrollKey ?: '<ROTATE_KEY_FIRST>');
@endphp
<div class="doc"><div class="optbar"><span class="otitle">Downloads</span><span class="osub">Everything needed to pair a lab PC with this server.</span><span class="grow"></span></div><div class="canvas ">
<section class="panel">
  @if($exeName)
    <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-live"/></svg></span><div class="grow"><b>Windows installer</b><div class="muted small">{{ $exeName }} · {{ $exeSize }}Windows 10 and 11</div></div><a class="btn btn-solid" href="/downloads/{{ $exeName }}" onclick="Alpine.store('toasts').add('Installer is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</a></div>
  @else
    <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-live"/></svg></span><div class="grow"><b>Windows installer</b><div class="muted small">No Windows installer package uploaded to storage yet</div></div><span class="chip plain">Not uploaded</span></div>
  @endif
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-terminal"/></svg></span><div class="grow"><b>Ubuntu and Debian installer</b><div class="muted small">linux.sh · installs the agent as a service · Xorg sessions for screen view</div></div><a class="btn" href="{{ route('install.linux') }}" onclick="Alpine.store('toasts').add('Script is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</a></div>
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-key"/></svg></span><div class="grow"><b>Lab certificate</b><div class="muted small">ca.crt · lets the lab hide AI summaries in search results{{ !empty($fingerprint) ? ' · SHA-256 ' . substr($fingerprint, 0, 23) . '…' : '' }}</div></div><a class="btn" href="{{ route('ca.cert') }}" onclick="Alpine.store('toasts').add('Certificate is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</a></div>
  <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-globe"/></svg></span><div class="grow"><b>Proxy configuration</b><div class="muted small">proxy.pac · for labs that use proxy-only mode</div></div><a class="btn" href="{{ route('proxy.pac') }}" onclick="Alpine.store('toasts').add('File is downloading.', 'info')"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</a></div>
  @foreach($files ?? [] as $f)
    @if($f['name'] !== $exeName)
      <div class="dl"><span class="ico"><svg class="i i-lg" aria-hidden="true"><use href="#i-download"/></svg></span><div class="grow"><b>{{ $f['name'] }}</b><div class="muted small">{{ $f['size_mb'] }} MB · Release artifact</div></div><a class="btn" href="/downloads/{{ $f['name'] }}"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Download</a></div>
    @endif
  @endforeach
</section>
<script>
window.XG_DL_PAGE = {
  win: @json($winCmd),
  lin: @json($linCmd),
};
</script>
<div class="cols-2">
  <section class="panel panel-pad stack" x-data="{ win: window.XG_DL_PAGE.win, lin: window.XG_DL_PAGE.lin }">
    <h2 class="h2">Silent install</h2>
    <div><div class="cmd-label">Windows (as administrator)</div><div class="cmd"><pre x-text="win"></pre><button class="btn btn-sm copy" @click="xgCopy(win, 'Copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div></div>
    <div><div class="cmd-label">Ubuntu / Debian</div><div class="cmd"><pre x-text="lin"></pre><button class="btn btn-sm copy" @click="xgCopy(lin, 'Copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div></div>
  </section>
  <section class="panel panel-pad stack"><h2 class="h2">After installing</h2>
    <ol class="steps-num"><li><b>The agent starts by itself</b><div class="muted small">It runs in the background.</div></li><li><b>Approve it here</b><div class="muted small">It appears on <a href="enroll.html">Add a PC</a> within a few seconds.</div></li><li><b>If someone ends it</b><div class="muted small">The PC shows as offline on the map and an alert is raised.</div></li></ol></section>
</div></div></div>
@endsection
