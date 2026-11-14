@extends('layouts.app', ['activePage' => 'enroll.html'])
@section('title', 'Add a PC')
@section('content')
@php
  $cccHost = $ccc ?? '192.168.0.51';
  $portSuffix = request()->getPort() && !in_array(request()->getPort(), [80, 443], true) ? ':' . request()->getPort() : ':8000';
  $baseUrl = (request()->isSecure() ? 'https://' : 'http://') . $cccHost . $portSuffix;
  $exeName = $setupFile ?? 'XephyGuard-Setup.exe';

  $livePending = isset($pending) && $pending->count() ? $pending->map(function ($e) {
      return [
          'id' => $e->id,
          'real' => true,
          'host' => $e->hostname,
          'os' => trim($e->os . ' ' . ($e->os_version ?? '')),
          'ip' => $e->ip ?? '—',
          'mac' => collect($e->macs ?? [])->first() ?? '—',
          'name' => $e->hostname,
      ];
  })->values()->all() : null;

  $livePcs = isset($pcs) && $pcs->count() ? $pcs->map(function ($p) {
      return [
          'id' => $p->id,
          'real' => true,
          'name' => $p->name,
          'host' => $p->hostname,
          'os' => trim($p->os . ' ' . ($p->os_version ?? '')),
          'ip' => $p->ip ?? '—',
          'agent' => $p->agent?->version ?? '0.2.0',
          'status' => $p->online() ? 'normal' : 'offline',
          'lastSeen' => $p->last_seen_at ? $p->last_seen_at->diffForHumans() : 'Never',
          'certExpires' => $p->agent?->cert_expires_at ? $p->agent->cert_expires_at->format('Y-m-d') : '2027-11-14',
          'retired' => $p->retired_at !== null,
          'editingName' => false,
      ];
  })->values()->all() : null;
@endphp
<div class="doc" x-data="{
  os: 'win', q: '',
  auto: @json((bool) ($lab?->auto_approve ?? true)),
  key: @json($key ?? 'XG-A77CFB-6554C8-489B53'),
  fp: @json($fingerprint ?? 'B2:8E:59:71:6C:33:9A:81:40:DE:FD:31:07:95:2E:8C:31:F9:67:8B:10:98:99:A2:05:4B:37:F1:C0:01:22:98'),
  macs: @json(!empty($lab?->auto_approve_macs) ? implode("\n", $lab->auto_approve_macs) : "70:85:c2:55:1a:40\nb4:2e:99:11:80:cc"),
  pending: {{ $livePending !== null ? json_encode($livePending) : '[
    { id: 1, real: false, host: \'LAB-PC-DESK25\', os: \'Windows 11 Pro\', ip: \'192.168.0.125\', mac: \'70:85:C2:55:1A:40\', name: \'PC-25\' },
    { id: 2, real: false, host: \'DESKTOP-KUET-09\', os: \'Ubuntu 24.04 LTS\', ip: \'192.168.0.126\', mac: \'B4:2E:99:11:80:CC\', name: \'PC-26\' }
  ]' }},
  enrolled: {{ $livePcs !== null ? json_encode($livePcs) : 'XG.pcs.map(p => ({ ...p, real: false, lastSeen: p.status === \"offline\" ? \"25m ago\" : \"Just now\", certExpires: \"2027-11-14\", retired: false, editingName: false }))' }},
  get cmd() { return this.os === 'win'
      ? @js($exeName) + ' /S /KEY=' + this.key + ' /CCC=' + @js($baseUrl) + ' /CAFP=' + this.fp
      : 'curl -fsSL ' + @js($baseUrl) + '/install/linux.sh | sudo bash -s -- --key ' + this.key; },
  get shown() { const q = this.q.toLowerCase(); return this.enrolled.filter(p => !q || (p.name + p.host + p.ip).toLowerCase().includes(q)); },
  approve(p) {
    if (p.real && window.xgApi) window.xgApi('/enroll/' + p.id + '/approve', { method: 'POST', body: JSON.stringify({ name: p.name }) });
    this.pending = this.pending.filter(x => x.id !== p.id);
    $store.toasts.add('Enrolled ' + (p.name || p.host) + '.', 'ok');
  },
  reject(p) {
    if (p.real && window.xgApi) window.xgApi('/enroll/' + p.id + '/reject', { method: 'POST' });
    this.pending = this.pending.filter(x => x.id !== p.id);
    $store.toasts.add('Turned away ' + p.host + '.', 'watch');
  },
  renamePc(p) {
    p.editingName = false;
    if (p.real && window.xgApi) window.xgApi('/pcs/' + p.id + '/rename', { method: 'POST', body: JSON.stringify({ name: p.name }) });
    $store.toasts.add('Renamed to ' + p.name + '.', 'ok');
  },
  retirePc(p) {
    if (!confirm('Retire ' + p.name + '? Its certificate stops working.')) return;
    if (p.real && window.xgApi) window.xgApi('/pcs/' + p.id + '/retire', { method: 'POST' });
    this.enrolled = this.enrolled.filter(x => x.id !== p.id);
    $store.toasts.add(p.name + ' retired.', 'watch');
  }
}"><div class="optbar"><span class="otitle">Add a PC</span><span class="osub">Install the agent, then approve the PC when it appears.</span><span class="grow"></span><a class="btn" href="downloads.html"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Downloads</a></div><div class="canvas ">
  

  <div class="cols-2">
    <section class="panel">
      <div class="panel-head"><h2 class="h2">1. Install the agent</h2></div>
      <div class="panel-body stack">
        <div><div class="cmd-label">Lab enrolment key</div>
          <div class="key">
            <code x-text="key"></code>
            <button type="button" class="btn btn-sm" @click="xgCopy(key, 'Key copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg> Copy</button>
            <form method="post" action="{{ route('enroll.rotate') }}" style="display:inline" onsubmit="return confirm('The old key stops working for new installs. Continue?')">
              @csrf
              <button type="submit" class="btn btn-sm btn-quiet">Rotate</button>
            </form>
          </div>
        </div>
        <div>
          <div class="seg" style="margin-bottom:10px"><button :aria-pressed="os === 'win'" @click="os = 'win'">Windows</button><button :aria-pressed="os === 'linux'" @click="os = 'linux'">Ubuntu / Debian</button></div>
          <div class="cmd"><pre x-text="cmd"></pre><button class="btn btn-sm copy" @click="xgCopy(cmd, 'Command copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div>
          <p class="help" x-show="os === 'win'">Run as administrator. Works from Group Policy or a disk image.</p>
          <p class="help" x-show="os === 'linux'" x-cloak>For a whole lab, use the Ansible role in <code>installers/ansible</code>.</p>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2 class="h2">2. Approve new PCs</h2>
        <span class="chip alert" x-show="pending.length" x-text="pending.length + ' waiting'"></span>
        <form method="post" action="{{ route('enroll.approve_all') }}" x-show="pending.length" style="display:inline" @submit="if(!{{ $livePending !== null ? 'true' : 'false' }}) { $event.preventDefault(); pending = []; $store.toasts.add('Approved everything waiting.', 'ok'); }">
          @csrf
          <button type="submit" class="btn btn-sm">Approve all</button>
        </form>
      </div>
      <template x-for="p in pending" :key="p.id">
        <div class="row" style="padding:14px 20px;border-bottom:1px solid var(--border);flex-wrap:nowrap;--gap:14px">
          <div class="grow" style="min-width:0"><div class="mono" style="font-weight:500" x-text="p.host"></div><div class="small muted" x-text="p.os + ' · ' + p.ip"></div></div>
          <input class="input input-sm" style="width:110px" x-model="p.name" aria-label="Display name">
          <button class="btn btn-sm btn-solid" @click="approve(p)">Approve</button><button class="btn btn-sm btn-quiet" @click="reject(p)">Reject</button>
        </div>
      </template>
      <div class="empty-state" x-show="!pending.length"><b>No PCs waiting</b>New installs appear here.</div>
      <form method="post" action="{{ route('enroll.auto') }}" class="panel-body stack" style="border-top:1px solid var(--border);background:var(--surface-2)">
        @csrf
        <label class="check"><span class="switch"><input type="checkbox" name="auto_approve" value="1" x-model="auto"><i></i></span> Approve known MAC addresses automatically</label>
        <div class="stack" style="--gap:8px" x-show="auto">
          <textarea name="macs" class="textarea mono" rows="3" x-model="macs"></textarea>
          <div><button type="submit" class="btn btn-sm">Save list</button></div>
        </div>
      </form>
    </section>
  </div>

  <section class="panel">
    <div class="panel-head"><h2 class="h2">Enrolled PCs</h2><span class="muted small" x-text="enrolled.length + ' total'"></span><input class="input input-sm" style="width:220px" placeholder="Search" x-model="q"></div>
    <div class="table-wrap"><table class="tbl">
      <thead><tr><th>PC</th><th>Computer</th><th>System</th><th>Address</th><th>Agent</th><th>Last seen</th><th>Cert expires</th><th></th></tr></thead>
      <tbody><template x-for="p in shown" :key="p.id"><tr :style="p.retired && 'opacity:.5'">
        <td class="name">
          <span class="dot" :class="p.status === 'offline' ? 'off' : 'ok'" style="margin-right:10px"></span>
          <template x-if="!p.editingName">
            <span><span x-text="p.name"></span> <button type="button" class="link-btn small muted" style="margin-left:6px" @click="p.editingName = true">Rename</button></span>
          </template>
          <template x-if="p.editingName">
            <span class="row" style="display:inline-flex;--gap:6px"><input class="input input-sm" style="width:110px" x-model="p.name" @keydown.enter="renamePc(p)"><button type="button" class="btn btn-sm" @click="renamePc(p)">Save</button></span>
          </template>
        </td>
        <td class="mono small" x-text="p.host"></td><td x-text="p.os"></td><td class="mono small" x-text="p.ip"></td>
        <td><span class="mono small" x-text="'v' + p.agent"></span></td>
        <td class="small muted" x-text="p.lastSeen || 'Just now'"></td>
        <td class="mono small muted" x-text="p.certExpires || '2027-11-14'"></td>
        <td class="right"><button class="btn btn-sm btn-quiet" x-show="!p.retired" @click="retirePc(p)">Retire</button><span class="small muted" x-show="p.retired">Retired</span></td></tr></template></tbody>
    </table></div>
  </section>
</div></div>
@endsection
