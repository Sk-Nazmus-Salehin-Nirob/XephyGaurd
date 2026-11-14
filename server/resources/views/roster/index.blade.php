@extends('layouts.app', ['activePage' => 'roster.html'])
@section('title', 'Roster')
@section('content')
@php
  $liveRows = isset($students) && $students->count() ? $students->getCollection()->map(function ($s) {
      return [
          'dbId' => $s->id,
          'id' => $s->student_number,
          'name' => $s->name,
          'login' => $s->login,
          'token' => substr((string) ($s->pseudonym ?? hash('sha256', (string) $s->student_number)), 0, 12),
          'consent' => $s->latestConsent ? ($s->latestConsent->granted ? 'granted' : 'declined') : 'declined',
          'ex' => $s->exempt ? ($s->exempt_reason ?? 'Accommodation') : '',
          'exOpen' => false,
      ];
  })->values()->all() : null;
@endphp
<div class="doc" x-data="{
  q: '', pseudo: @json((bool) ($pseudonymize ?? true)),
  rows: {{ $liveRows !== null ? json_encode($liveRows) : '[
    { dbId: null, id: \'2107001\', name: \'Rupom Hasan\', login: \'std_210701\', token: \'c8f92a10b4de\', consent: \'granted\', ex: \'\', exOpen: false },
    { dbId: null, id: \'2107002\', name: \'Sadia Islam\', login: \'std_210712\', token: \'9b231ff08a71\', consent: \'granted\', ex: \'\', exOpen: false },
    { dbId: null, id: \'2107003\', name: \'Imran Hossain\', login: \'std_210713\', token: \'27d0e4b9c613\', consent: \'granted\', ex: \'\', exOpen: false },
    { dbId: null, id: \'2107004\', name: \'Nusrat Jahan\', login: \'std_210714\', token: \'e41b7a02d958\', consent: \'declined\', ex: \'\', exOpen: false },
    { dbId: null, id: \'2107007\', name: \'Siyam Ahmed\', login: \'std_210712\', token: \'5a31de6701ba\', consent: \'declined\', ex: \'Speech-to-text tool\', exOpen: false },
    { dbId: null, id: \'2107009\', name: \'Farhana Akter\', login: \'std_210719\', token: \'0f6c8d31ae72\', consent: \'granted\', ex: \'\', exOpen: false }
  ]' }},
  get shown() { const q = this.q.toLowerCase(); return this.rows.filter(r => !q || (r.id + r.name + r.login).toLowerCase().includes(q)); },
  togglePseudo() {
    if (window.xgApi) window.xgApi('/roster/pseudonymize', { method: 'POST', body: JSON.stringify({ enabled: this.pseudo }) });
    $store.toasts.add(this.pseudo ? 'Pseudonyms enabled in exports.' : 'Student numbers used in exports.', 'ok');
  },
  setConsent(r, status) {
    r.consent = status;
    if (r.dbId && window.xgApi) {
      window.xgApi('/roster/' + r.dbId + '/consent', { method: 'POST', body: JSON.stringify({ granted: status === 'granted' }) });
    }
    $store.toasts.add('Consent updated for ' + r.name + '.', 'ok');
  },
  saveExempt(r, exempt) {
    if (!exempt) { r.ex = ''; }
    r.exOpen = false;
    if (r.dbId && window.xgApi) {
      window.xgApi('/roster/' + r.dbId + '/exempt', { method: 'POST', body: JSON.stringify({ exempt: !!r.ex, reason: r.ex || null }) });
    }
    $store.toasts.add('Saved.', 'ok');
  }
}">
  <form id="xg-roster-import" method="post" action="{{ route('roster.import') }}" enctype="multipart/form-data" style="display:none">
    @csrf
    <input id="csv" name="file" type="file" accept=".csv" hidden onchange="this.form.submit()">
  </form>
  <div class="optbar"><span class="otitle">Roster</span><span class="osub">Maps lab logins to students. Exports use the pseudonym only.</span><span class="grow"></span><button class="btn btn-solid" onclick="document.getElementById('csv').click()"><svg class="i i-sm" aria-hidden="true"><use href="#i-upload"/></svg> Import CSV</button></div><div class="canvas ">
  
  <div class="toolbar"><input class="input input-sm" style="width:280px" placeholder="Search ID, name or login" x-model="q"><span class="grow"></span><label class="check small"><span class="switch"><input type="checkbox" x-model="pseudo" @change="togglePseudo()"><i></i></span> Pseudonyms in research exports</label></div>
  <section class="panel">
    <div class="table-wrap"><table class="tbl">
      <thead><tr><th>ID</th><th>Name</th><th>Login</th><th>Pseudonym</th><th>Research consent</th><th>Accommodation</th></tr></thead>
      <tbody><template x-for="r in shown" :key="r.id"><tr>
        <td class="mono small" x-text="r.id"></td><td class="name" x-text="r.name"></td><td class="mono small" x-text="r.login"></td><td class="mono small muted" x-text="pseudo ? r.token : 'Not used'"></td>
        <td><div class="seg"><button :aria-pressed="r.consent === 'granted'" @click="setConsent(r, 'granted')">Yes</button><button :aria-pressed="r.consent === 'declined'" @click="setConsent(r, 'declined')">No</button></div></td>
        <td>
          <template x-if="r.ex && !r.exOpen"><span class="row"><span class="chip info" x-text="r.ex"></span><button class="btn btn-sm btn-quiet" @click="saveExempt(r, false)">Remove</button></span></template>
          <template x-if="!r.ex && !r.exOpen"><button class="link-btn" @click="r.exOpen = true">Add</button></template>
          <template x-if="r.exOpen"><span class="row"><input class="input input-sm" style="width:200px" placeholder="What does the student need?" x-model="r.ex" @keydown.enter="saveExempt(r, true)"><button class="btn btn-sm" @click="saveExempt(r, true)">Save</button></span></template>
        </td></tr></template></tbody>
    </table></div>
    <div class="tbl-foot"><span x-text="'Showing ' + shown.length + ' of ' + ({{ isset($students) && $students->total() ? $students->total() : 65 }}) + ' students'"></span><div class="pager"><button aria-current="page">1</button><button>2</button><button>3</button></div></div>
  </section>
</div></div>
@endsection
