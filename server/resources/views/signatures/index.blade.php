@extends('layouts.app', ['activePage' => 'signatures.html'])
@section('title', 'Blocklists and rules')
@section('content')
<div class="doc" x-data="{
  tab: 'sites', cat: 'all', q: '', newDomain: '', newCat: 'custom', rq: '', rk: 'all', importOpen: false,
  counts: { all: 285, ai: 169, ide: 47, marketplace: 8, doh: 38, vpn: 23, custom: 0 },
  sites: [
    { id: 1, d: 'ai.google.dev', c: 'ai', s: 'built-in', off: false }, { id: 2, d: 'ai21.com', c: 'ai', s: 'built-in', off: false },
    { id: 3, d: 'aistudio.google.com', c: 'ai', s: 'built-in', off: false }, { id: 4, d: 'chatgpt.com', c: 'ai', s: 'built-in', off: false },
    { id: 5, d: 'claude.ai', c: 'ai', s: 'built-in', off: false }, { id: 6, d: 'cdn.grok.com', c: 'ai', s: 'built-in', off: false },
    { id: 7, d: 'api.githubcopilot.com', c: 'ide', s: 'built-in', off: false }, { id: 8, d: 'codeium.com', c: 'ide', s: 'built-in', off: true },
    { id: 9, d: 'replit.com', c: 'marketplace', s: 'built-in', off: false }, { id: 10, d: 'dns.google', c: 'doh', s: 'built-in', off: false },
    { id: 11, d: 'cloudflare-dns.com', c: 'doh', s: 'built-in', off: false }, { id: 12, d: 'nordvpn.com', c: 'vpn', s: 'built-in', off: false }
  ],
  rules: [
    { id: 'proc.ollama', kind: 'process', sev: 'critical', desc: 'Ollama local AI server', on: true }, { id: 'proc.llamacpp', kind: 'process', sev: 'critical', desc: 'llama.cpp local server', on: true },
    { id: 'proc.lmstudio', kind: 'process', sev: 'critical', desc: 'LM Studio local AI', on: true }, { id: 'web.grok', kind: 'traffic', sev: 'high', desc: 'Grok (xAI) stream', on: true },
    { id: 'web.chatgpt', kind: 'traffic', sev: 'high', desc: 'ChatGPT stream', on: true }, { id: 'net.second_route', kind: 'network', sev: 'critical', desc: 'A second network route appeared', on: true },
    { id: 'hw.adapter_added', kind: 'device', sev: 'critical', desc: 'Extra network adapter or tethered phone', on: true }, { id: 'dev.usb_device', kind: 'device', sev: 'low', desc: 'External USB device attached', on: true },
    { id: 'tamper.helper_terminated', kind: 'agent', sev: 'high', desc: 'Session helper was ended', on: true }, { id: 'tamper.machine_silent', kind: 'agent', sev: 'high', desc: 'No heartbeat from the agent', on: true },
    { id: 'paste.large', kind: 'clipboard', sev: 'low', desc: 'Paste above the size limit in Settings', on: true }, { id: 'ext.ai_assistant', kind: 'extension', sev: 'medium', desc: 'AI assistant browser extension', on: false }
  ],
  versions: [
    { v: '2026.11.08-b2a25a', note: 'Added Grok and LM Studio rules', when: 'Today 09:14', active: true },
    { v: '2026.11.05-5ac910', note: 'Baseline profiles and rules', when: '3 days ago', active: false }
  ],
  lab(k) { return ({ all: 'All', ai: 'AI', ide: 'Editor', marketplace: 'Marketplace', doh: 'Encrypted DNS', vpn: 'VPN', custom: 'Custom' })[k] || k; },
  get catKeys() { return Object.keys(this.counts); },
  get shown() { const q = this.q.toLowerCase(); return this.sites.filter(s => (this.cat === 'all' || s.c === this.cat) && (!q || s.d.includes(q))); },
  get rshown() { const q = this.rq.toLowerCase(); return this.rules.filter(r => (this.rk === 'all' || r.kind === this.rk) && (!q || (r.id + r.desc).toLowerCase().includes(q))); },
  get kinds() { return ['all', ...new Set(this.rules.map(r => r.kind))]; },
  addSite() { const d = this.newDomain.trim().toLowerCase(); if (!d) return; this.sites.unshift({ id: Date.now(), d, c: this.newCat, s: 'custom', off: false }); this.newDomain = ''; $store.toasts.add(d + ' is now blocked.', 'ok'); }
}"><div class="optbar"><span class="otitle">Blocklists and rules</span><span class="osub">What gets blocked and noticed on each PC.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="tabs" role="tablist"><button role="tab" :aria-selected="tab === 'sites'" @click="tab = 'sites'">Websites</button><button role="tab" :aria-selected="tab === 'rules'" @click="tab = 'rules'">Detection rules <span class="count" x-text="rules.length"></span></button><button role="tab" :aria-selected="tab === 'versions'" @click="tab = 'versions'">Published versions</button></div>

  <section x-show="tab === 'sites'">
    <div class="toolbar">
      <div class="pills"><template x-for="k in catKeys" :key="k"><button class="pill" :aria-pressed="cat === k" @click="cat = k"><span x-text="lab(k)"></span> <span class="n" x-text="counts[k]"></span></button></template></div>
      <span class="grow"></span><input class="input input-sm" style="width:220px" placeholder="Search sites" x-model="q"><button class="btn btn-sm" @click="importOpen = !importOpen"><svg class="i i-sm" aria-hidden="true"><use href="#i-upload"/></svg> Import list</button>
    </div>
    <form class="row" style="padding:12px 20px;background:var(--surface-2);border-bottom:1px solid var(--border)" @submit.prevent="addSite()">
      <input class="input input-sm mono" style="flex:1;min-width:220px" placeholder="Block a site, e.g. example.com" x-model="newDomain"><select class="select select-sm" style="width:150px" x-model="newCat"><option value="custom">Custom</option><option value="ai">AI</option><option value="ide">Editor</option><option value="marketplace">Marketplace</option><option value="vpn">VPN</option></select><button class="btn btn-sm btn-solid">Block site</button>
    </form>
    <div class="panel-body stack" x-show="importOpen" x-cloak style="background:var(--surface-2);border-bottom:1px solid var(--border)"><textarea class="textarea mono" rows="4" placeholder="One domain per line"></textarea><div class="row"><button class="btn btn-sm btn-solid" @click="importOpen = false; $store.toasts.add('List imported.', 'ok')">Import</button><button class="btn btn-sm btn-quiet" @click="importOpen = false">Cancel</button></div></div>
    <section class="panel"><div class="table-wrap"><table class="tbl">
      <thead><tr><th>Site</th><th>Type</th><th>Source</th><th class="right">Blocked</th></tr></thead>
      <tbody><template x-for="s in shown" :key="s.id"><tr :style="s.off && 'opacity:.5'">
        <td class="mono" x-text="s.d"></td><td><span class="chip" :class="s.c === 'ai' && 'alert'" x-text="lab(s.c)"></span></td><td class="muted" x-text="s.s"></td>
        <td class="right"><label class="switch"><input type="checkbox" :checked="!s.off" @change="s.off = !s.off" :aria-label="'Block ' + s.d"><i></i></label></td></tr></template></tbody>
    </table></div><div class="tbl-foot">Changes apply to PCs within seconds.</div></section>
  </section>

  <section x-show="tab === 'rules'" x-cloak>
    <div class="toolbar"><div class="pills"><template x-for="k in kinds" :key="k"><button class="pill" :aria-pressed="rk === k" @click="rk = k" style="text-transform:capitalize" x-text="k"></button></template></div><span class="grow"></span><input class="input input-sm" style="width:220px" placeholder="Search rules" x-model="rq"></div>
    <section class="panel"><div class="table-wrap"><table class="tbl">
      <thead><tr><th>Rule</th><th>Severity</th><th>What it catches</th><th class="right">Enabled</th></tr></thead>
      <tbody><template x-for="r in rshown" :key="r.id"><tr :style="!r.on && 'opacity:.5'"><td><div class="mono" style="font-weight:500" x-text="r.id"></div><div class="tiny muted" style="text-transform:capitalize" x-text="r.kind"></div></td><td><span class="sev" :class="r.sev" x-text="r.sev"></span></td><td x-text="r.desc"></td><td class="right"><label class="switch"><input type="checkbox" x-model="r.on" :aria-label="'Enable ' + r.id"><i></i></label></td></tr></template></tbody>
    </table></div><div class="tbl-foot">Showing <span x-text="rshown.length"></span> of 72 rules</div></section>
  </section>

  <section x-show="tab === 'versions'" x-cloak>
    <div class="panel panel-pad stack" style="max-width:none"><div><h2 class="h2">Publish the current rules</h2><p class="muted small" style="margin-top:2px">Signs the blocklists and rules and sends them to every PC.</p></div>
      <div class="row"><input class="input" style="max-width:420px" placeholder="What changed? (optional)"><button class="btn btn-solid" @click="if(confirm('Publish to all PCs?')) $store.toasts.add('New version signed and sent.', 'ok')">Publish to PCs</button></div></div>
    <section class="panel"><table class="tbl"><thead><tr><th>Version</th><th>Note</th><th>Published</th><th></th></tr></thead><tbody>
      <template x-for="v in versions" :key="v.v"><tr><td class="mono small" style="font-weight:500" x-text="v.v"></td><td x-text="v.note"></td><td class="muted" x-text="v.when"></td><td class="right"><span class="chip ok" x-show="v.active">In use</span><button class="btn btn-sm" x-show="!v.active" @click="if(confirm('Roll every PC back to this version?')) $store.toasts.add('Rolled back.', 'watch')">Roll back</button></td></tr></template></tbody></table></section>
  </section>
</div></div>
@endsection
