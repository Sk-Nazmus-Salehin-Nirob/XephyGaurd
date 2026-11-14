@extends('layouts.app', ['activePage' => 'users.html'])
@section('title', 'Staff accounts')
@section('content')
@php
  $liveUsers = isset($users) && $users->count() ? $users->map(function ($u) {
      return [
          'id' => $u->id,
          'name' => $u->name,
          'email' => $u->email,
          'role' => $u->role,
          'on' => (bool) ($u->active ?? true),
          'pwOpen' => false,
          'pw' => '',
      ];
  })->values()->all() : null;
@endphp
<div class="doc" x-data="{
  users: {{ $liveUsers !== null ? json_encode($liveUsers) : '[ { id: null, name: \'KUET Admin\', email: \'tahmid.tts@gmail.com\', role: \'admin\', on: true, pwOpen: false, pw: \'\' }, { id: null, name: \'Course Instructor\', email: \'instructor@cse.kuet.ac.bd\', role: \'instructor\', on: true, pwOpen: false, pw: \'\' }, { id: null, name: \'Lab Assistant\', email: \'assistant@cse.kuet.ac.bd\', role: \'assistant\', on: true, pwOpen: false, pw: \'\' } ]' }},
  addOpen: false,
  caps: [['Watch the live lab', 1, 1, 1], ['View student screens', 0, 1, 1], ['Enrol and approve PCs', 1, 0, 1], ['Start sessions and edit the timetable', 0, 1, 1], ['Reports and roster', 0, 1, 1], ['Blocklists, settings and staff', 0, 0, 1]],
  initials(n) { return (n || '').split(' ').slice(0, 2).map(w => w[0] || '').join('').toUpperCase(); },
  saveUser(u) {
    if (u.id && window.xgApi) {
      const payload = { name: u.name, email: u.email, role: u.role, active: u.on };
      if (u.pw && u.pw.length >= 10) payload.password = u.pw;
      window.xgApi('/users/' + u.id, { method: 'POST', body: JSON.stringify(payload) });
    }
    u.pwOpen = false;
    u.pw = '';
    $store.toasts.add('Saved ' + u.name + '.', 'ok');
  }
}"><div class="optbar"><span class="otitle">Staff accounts</span><span class="osub">Give each person the smallest role that lets them do their job.</span><span class="grow"></span><button class="btn btn-solid" @click="addOpen = true"><svg class="i i-sm" aria-hidden="true"><use href="#i-plus"/></svg> Add a person</button></div><div class="canvas ">
  
  <section class="panel"><div class="table-wrap"><table class="tbl">
    <thead><tr><th>Person</th><th>Role</th><th>Can sign in</th><th></th></tr></thead>
    <tbody><template x-for="u in users" :key="u.email"><tr :style="!u.on && 'opacity:.55'">
      <td><div class="row" style="flex-wrap:nowrap;--gap:12px"><span class="avatar" x-text="initials(u.name)"></span><div><div class="name" x-text="u.name"></div><div class="small muted" x-text="u.email"></div></div></div></td>
      <td><select class="select select-sm" style="width:150px" x-model="u.role"><option>assistant</option><option>instructor</option><option>admin</option></select></td>
      <td><label class="switch"><input type="checkbox" x-model="u.on" :aria-label="'Active: ' + u.name"><i></i></label></td>
      <td class="right nw">
        <template x-if="u.pwOpen">
          <input type="password" class="input input-sm" style="width:150px;margin-right:6px" placeholder="New password (10+)" x-model="u.pw">
        </template>
        <button class="btn btn-sm btn-quiet" @click="u.pwOpen = !u.pwOpen" x-text="u.pwOpen ? 'Cancel' : 'Reset password'"></button>
        <button class="btn btn-sm" @click="saveUser(u)">Save</button>
      </td></tr></template></tbody>
  </table></div></section>
  <section class="panel"><div class="panel-head"><h2 class="h2">What each role can do</h2></div>
    <table class="tbl matrix"><thead><tr><th>Ability</th><th>Assistant</th><th>Instructor</th><th>Admin</th></tr></thead>
      <tbody><template x-for="c in caps" :key="c[0]"><tr><td x-text="c[0]"></td><template x-for="v in c.slice(1)"><td><span class="yes" x-show="v"><svg class="i i-sm" aria-hidden="true"><use href="#i-check"/></svg></span><span class="no" x-show="!v">–</span></td></template></tr></template></tbody></table></section>

  <div class="overlay" x-show="addOpen" x-cloak x-transition.opacity @click.self="addOpen = false" @keydown.escape.window="addOpen = false">
    <div class="modal" role="dialog" aria-label="Add a person">
      <div class="modal-head"><span class="h2">Add a person</span><button class="xbtn" @click="addOpen = false" aria-label="Close"><svg class="i" aria-hidden="true"><use href="#i-x"/></svg></button></div>
      <form method="post" action="{{ route('admin.users.save') }}">
        @csrf
        <input type="hidden" name="active" value="1">
        <div class="modal-body stack">
          <label class="field"><span>Name</span><input name="name" class="input" required></label>
          <label class="field"><span>Institutional email</span><input name="email" class="input" type="email" required></label>
          <div class="form-grid">
            <label class="field"><span>Role</span><select name="role" class="select"><option value="assistant">assistant</option><option value="instructor">instructor</option><option value="admin">admin</option></select></label>
            <label class="field"><span>Temporary password</span><input name="password" class="input" type="password" minlength="10" required></label>
          </div>
        </div>
        <div class="modal-foot"><button type="button" class="btn" @click="addOpen = false">Cancel</button><button type="submit" class="btn btn-solid">Create account</button></div>
      </form>
    </div>
  </div>
</div></div>
@endsection
