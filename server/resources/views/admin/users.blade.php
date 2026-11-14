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
  })->values()->all() : [];
@endphp
<script type="application/json" id="xg-page-data">{!! json_encode(['users' => $liveUsers], JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) !!}</script>
<div class="doc" x-data="usersPage"><div class="optbar"><span class="otitle">Staff accounts</span><span class="osub">Give each person the smallest role that lets them do their job.</span><span class="grow"></span><button class="btn btn-solid" @click="addOpen = true"><svg class="i i-sm" aria-hidden="true"><use href="#i-plus"/></svg> Add a person</button></div><div class="canvas ">
  @if ($errors->any())
  <div class="note warn" style="margin-bottom:16px"><svg class="i i-sm" aria-hidden="true"><use href="#i-warn"/></svg><span>{{ $errors->first() }}</span></div>
  @endif
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
      </td></tr></template>
      <template x-if="!users.length"><tr><td colspan="4" class="muted" style="padding:18px 16px">No staff accounts found.</td></tr></template>
    </tbody>
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
