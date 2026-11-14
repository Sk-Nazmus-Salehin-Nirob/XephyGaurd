@extends('layouts.app', ['activePage' => 'enroll.html'])
@section('title', 'Add a PC')
@section('content')
<div class="doc" x-data="{
  os: 'win', q: '', auto: true, key: 'XG-A77CFB-6554C8-489B53',
  fp: 'B2:8E:59:71:6C:33:9A:81:40:DE:FD:31:07:95:2E:8C:31:F9:67:8B:10:98:99:A2:05:4B:37:F1:C0:01:22:98',
  macs: '70:85:c2:55:1a:40\nb4:2e:99:11:80:cc',
  pending: [
    { id: 1, host: 'LAB-PC-DESK25', os: 'Windows 11 Pro', ip: '192.168.0.125', mac: '70:85:C2:55:1A:40', name: 'PC-25' },
    { id: 2, host: 'DESKTOP-KUET-09', os: 'Ubuntu 24.04 LTS', ip: '192.168.0.126', mac: 'B4:2E:99:11:80:CC', name: 'PC-26' }
  ],
  get cmd() { return this.os === 'win'
      ? 'XephyGuard-Setup.exe /S /KEY=' + this.key + ' /CCC=http://192.168.0.51:8000 /CAFP=' + this.fp
      : 'curl -fsSL http://192.168.0.51:8000/install/linux.sh | sudo bash -s -- --key ' + this.key; },
  get shown() { const q = this.q.toLowerCase(); return XG.pcs.filter(p => !q || (p.name + p.host + p.ip).toLowerCase().includes(q)); },
  approve(p) { this.pending = this.pending.filter(x => x.id !== p.id); $store.toasts.add('Enrolled ' + (p.name || p.host) + '.', 'ok'); },
  reject(p) { this.pending = this.pending.filter(x => x.id !== p.id); $store.toasts.add('Turned away ' + p.host + '.', 'watch'); }
}"><div class="optbar"><span class="otitle">Add a PC</span><span class="osub">Install the agent, then approve the PC when it appears.</span><span class="grow"></span><a class="btn" href="downloads.html"><svg class="i i-sm" aria-hidden="true"><use href="#i-download"/></svg> Downloads</a></div><div class="canvas ">
  

  <div class="cols-2">
    <section class="panel">
      <div class="panel-head"><h2 class="h2">1. Install the agent</h2></div>
      <div class="panel-body stack">
        <div><div class="cmd-label">Lab enrolment key</div>
          <div class="key"><code x-text="key"></code><button class="btn btn-sm" @click="xgCopy(key, 'Key copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg> Copy</button><button class="btn btn-sm btn-quiet" @click="if(confirm('The old key stops working for new installs. Continue?')) $store.toasts.add('New key created.', 'ok')">Rotate</button></div></div>
        <div>
          <div class="seg" style="margin-bottom:10px"><button :aria-pressed="os === 'win'" @click="os = 'win'">Windows</button><button :aria-pressed="os === 'linux'" @click="os = 'linux'">Ubuntu / Debian</button></div>
          <div class="cmd"><pre x-text="cmd"></pre><button class="btn btn-sm copy" @click="xgCopy(cmd, 'Command copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg></button></div>
          <p class="help" x-show="os === 'win'">Run as administrator. Works from Group Policy or a disk image.</p>
          <p class="help" x-show="os === 'linux'" x-cloak>For a whole lab, use the Ansible role in <code>installers/ansible</code>.</p>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head"><h2 class="h2">2. Approve new PCs</h2><span class="chip alert" x-show="pending.length" x-text="pending.length + ' waiting'"></span><button class="btn btn-sm" x-show="pending.length" @click="pending = []; $store.toasts.add('Approved everything waiting.', 'ok')">Approve all</button></div>
      <template x-for="p in pending" :key="p.id">
        <div class="row" style="padding:14px 20px;border-bottom:1px solid var(--border);flex-wrap:nowrap;--gap:14px">
          <div class="grow" style="min-width:0"><div class="mono" style="font-weight:500" x-text="p.host"></div><div class="small muted" x-text="p.os + ' · ' + p.ip"></div></div>
          <input class="input input-sm" style="width:110px" x-model="p.name" aria-label="Display name">
          <button class="btn btn-sm btn-solid" @click="approve(p)">Approve</button><button class="btn btn-sm btn-quiet" @click="reject(p)">Reject</button>
        </div>
      </template>
      <div class="empty-state" x-show="!pending.length"><b>No PCs waiting</b>New installs appear here.</div>
      <div class="panel-body stack" style="border-top:1px solid var(--border);background:var(--surface-2)">
        <label class="check"><span class="switch"><input type="checkbox" x-model="auto"><i></i></span> Approve known MAC addresses automatically</label>
        <template x-if="auto"><div class="stack" style="--gap:8px"><textarea class="textarea mono" rows="3" x-model="macs"></textarea><div><button class="btn btn-sm" @click="$store.toasts.add('Saved.', 'ok')">Save list</button></div></div></template>
      </div>
    </section>
  </div>

  <section class="panel">
    <div class="panel-head"><h2 class="h2">Enrolled PCs</h2><span class="muted small" x-text="XG.pcs.length + ' total'"></span><input class="input input-sm" style="width:220px" placeholder="Search" x-model="q"></div>
    <div class="table-wrap"><table class="tbl">
      <thead><tr><th>PC</th><th>Computer</th><th>System</th><th>Address</th><th>Agent</th><th></th></tr></thead>
      <tbody><template x-for="p in shown" :key="p.id"><tr>
        <td class="name"><span class="dot" :class="p.status === 'offline' ? 'off' : 'ok'" style="margin-right:10px"></span><span x-text="p.name"></span></td>
        <td class="mono small" x-text="p.host"></td><td x-text="p.os"></td><td class="mono small" x-text="p.ip"></td>
        <td><span class="mono small" x-text="'v' + p.agent"></span></td>
        <td class="right"><button class="btn btn-sm btn-quiet" @click="if(confirm('Retire ' + p.name + '? Its certificate stops working.')) $store.toasts.add(p.name + ' retired.', 'watch')">Retire</button></td></tr></template></tbody>
    </table></div>
  </section>
</div></div>
@endsection