@extends('layouts.app', ['activePage' => 'share.html'])
@section('title', 'Shared clipboard')
@section('content')
@php
  $defaultHist = [
      ['t' => '12:01', 'v' => 'g++ -std=c++17 main.cpp -o main && ./main', 'cmd' => true],
      ['t' => '11:34', 'v' => 'Exam sheet: files.kuet.ac.bd/cser/q1.pdf', 'cmd' => false],
      ['t' => '11:20', 'v' => 'Use the provided header file only.', 'cmd' => false],
  ];
  $initialHist = !empty($history) ? $history : $defaultHist;
@endphp
<div class="doc" x-data="{
  text: @json($text ?? ''),
  cmd: false,
  editing: false,
  last: @json($updatedAt ?? 'Today 12:01 by KUET admin'),
  hist: @json($initialHist),
  init() {
    setInterval(async () => {
      if (this.editing) return;
      const r = await (window.xgApi ? window.xgApi('/share/raw') : null);
      if (r && r.ok && r.data) {
        if (r.data.updated_at && r.data.updated_at !== 'Never') this.last = r.data.updated_at;
        if (Array.isArray(r.data.history) && r.data.history.length) this.hist = r.data.history;
      }
    }, 2500);
  },
  async send() {
    if (!this.text.trim()) return;
    const v = this.text;
    const nowT = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    this.hist.unshift({ t: nowT, v: v, cmd: this.cmd });
    if (window.xgApi) {
      const r = await window.xgApi('/share', { method: 'POST', body: JSON.stringify({ text: v, cmd: this.cmd }) });
      if (r && r.ok && r.data && r.data.updated_at) this.last = r.data.updated_at;
      else this.last = 'Today ' + nowT + ' by KUET admin';
    } else {
      this.last = 'Today ' + nowT + ' by KUET admin';
    }
    this.text = '';
    this.editing = false;
    $store.toasts.add('Shared with all online PCs.', 'ok');
  }
}"><div class="optbar"><span class="otitle">Shared clipboard</span><span class="osub">Send text, commands or links to every PC in one step.</span><span class="grow"></span></div><div class="canvas narrow">
  
  <section class="panel" style="border-radius:0">
    <div class="panel-head"><h2 class="h2">New share</h2><span class="small muted" x-text="'Last: ' + last"></span></div>
    <div class="panel-body stack">
      <textarea class="textarea" :class="cmd && 'mono'" rows="5" placeholder="Paste text, a command, or a link…" x-model="text" @focus="editing = true" @blur="editing = false"></textarea>
      <div class="row"><label class="check"><span class="switch"><input type="checkbox" x-model="cmd"><i></i></span> Show as a command</label><span class="grow"></span>
        <button class="btn" @click="text = ''">Clear</button><button class="btn btn-solid" @click="send()"><svg class="i i-sm" aria-hidden="true"><use href="#i-send"/></svg> Share with all PCs</button></div>
    </div>
  </section>
  <section class="panel" style="border-radius:0">
    <div class="panel-head"><h2 class="h2">Recent shares</h2></div>
    <template x-for="h in hist" :key="h.t + h.v"><div class="row" style="padding:12px 20px;border-bottom:1px solid var(--border);--gap:14px;flex-wrap:nowrap"><span class="mono small muted" x-text="h.t"></span><span class="grow" style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" :class="h.cmd && 'mono small'" x-text="h.v"></span><button class="btn btn-sm" @click="xgCopy(h.v, 'Copied')"><svg class="i i-sm" aria-hidden="true"><use href="#i-copy"/></svg> Copy</button></div></template>
  </section>
</div></div>
@endsection
