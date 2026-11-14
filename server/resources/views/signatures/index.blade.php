@extends('layouts.app', ['activePage' => 'signatures.html'])
@section('title', 'Blocklists and rules')
@section('content')
@php
  $liveSites = isset($entries) && $entries->count() ? $entries->getCollection()->map(function ($e) {
      return [
          'id' => $e->id,
          'real' => true,
          'd' => $e->value,
          'c' => $e->category,
          's' => $e->source ?? 'built-in',
          'off' => !$e->enabled,
      ];
  })->values()->all() : [];

  $liveCounts = isset($counts) ? [
      'all' => (int) $counts->sum(),
      'ai' => (int) ($counts['ai'] ?? 0),
      'ide' => (int) ($counts['ide'] ?? 0),
      'marketplace' => (int) ($counts['marketplace'] ?? 0),
      'doh' => (int) ($counts['doh'] ?? 0),
      'vpn' => (int) ($counts['vpn'] ?? 0),
      'custom' => (int) ($counts['custom'] ?? 0),
  ] : ['all' => 0, 'ai' => 0, 'ide' => 0, 'marketplace' => 0, 'doh' => 0, 'vpn' => 0, 'custom' => 0];

  $liveRules = isset($rules) && $rules->count() ? $rules->map(function ($r) {
      return [
          'dbId' => $r->id,
          'id' => $r->rule_id,
          'kind' => $r->kind,
          'sev' => $r->severity,
          'desc' => $r->description ?? '',
          'on' => (bool) $r->enabled,
          'definition' => json_encode($r->definition ?? [], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES),
          'actions' => array_values($r->actions['test'] ?? ['log', 'alert']),
      ];
  })->values()->all() : [];

  $liveVersions = isset($versions) && $versions->count() ? $versions->map(function ($v) {
      return [
          'id' => $v->id,
          'v' => $v->version,
          'note' => $v->note ?: 'Published signature bundle',
          'when' => $v->created_at?->diffForHumans() ?? 'Recently',
          'active' => (bool) $v->active,
      ];
  })->values()->all() : [];
@endphp
<script type="application/json" id="xg-page-data">{!! json_encode([
  'cat' => !empty($category) ? $category : 'all',
  'q' => request()->string('q')->toString(),
  'counts' => $liveCounts,
  'sites' => $liveSites,
  'rules' => $liveRules,
  'versions' => $liveVersions,
  'hasPages' => isset($entries) && $entries->hasPages(),
], JSON_HEX_TAG | JSON_HEX_AMP | JSON_HEX_APOS | JSON_HEX_QUOT) !!}</script>
<div class="doc" x-data="sigPage"><div class="optbar"><span class="otitle">Blocklists and rules</span><span class="osub">What gets blocked and noticed on each PC.</span><span class="grow"></span></div><div class="canvas ">
  @if ($errors->any() || session('error'))
  <div class="note warn" style="margin-bottom:16px"><svg class="i i-sm" aria-hidden="true"><use href="#i-warn"/></svg><span>{{ session('error') ?: $errors->first() }}</span></div>
  @endif
  <div class="tabs" role="tablist"><button role="tab" :aria-selected="tab === 'sites'" @click="tab = 'sites'">Websites</button><button role="tab" :aria-selected="tab === 'rules'" @click="tab = 'rules'">Detection rules <span class="count" x-text="rules.length"></span></button><button role="tab" :aria-selected="tab === 'versions'" @click="tab = 'versions'">Published versions</button></div>

  <section x-show="tab === 'sites'">
    <div class="toolbar">
      <div class="pills"><template x-for="k in catKeys" :key="k"><button class="pill" :aria-pressed="cat === k" @click="selectCat(k)"><span x-text="lab(k)"></span> <span class="n" x-text="counts[k]"></span></button></template></div>
      <span class="grow"></span><input class="input input-sm" style="width:220px" placeholder="Search sites (Enter for all)" x-model="q" @keydown.enter.prevent="searchSites()"><button class="btn btn-sm" @click="importOpen = !importOpen"><svg class="i i-sm" aria-hidden="true"><use href="#i-upload"/></svg> Import list</button>
    </div>
    <form method="post" action="{{ route('blocklist.add') }}" class="row" style="padding:12px 20px;background:var(--surface-2);border-bottom:1px solid var(--border)">
      @csrf
      <input name="value" class="input input-sm mono" style="flex:1;min-width:220px" placeholder="Block a site, e.g. example.com" x-model="newDomain" required>
      <select name="category" class="select select-sm" style="width:150px" x-model="newCat"><option value="custom">Custom</option><option value="ai">AI</option><option value="ide">Editor</option><option value="marketplace">Marketplace</option><option value="doh">Encrypted DNS</option><option value="vpn">VPN</option></select>
      <button type="submit" class="btn btn-sm btn-solid">Block site</button>
    </form>
    <form method="post" action="{{ route('blocklist.import') }}" enctype="multipart/form-data" class="panel-body stack" x-show="importOpen" x-cloak style="background:var(--surface-2);border-bottom:1px solid var(--border)">
      @csrf
      <div class="row">
        <label class="field" style="width:180px"><span>Category</span><select name="category" class="select select-sm" x-model="newCat"><option value="custom">Custom</option><option value="ai">AI</option><option value="ide">Editor</option><option value="marketplace">Marketplace</option><option value="doh">Encrypted DNS</option><option value="vpn">VPN</option></select></label>
        <label class="field"><span>Or upload file</span><input type="file" name="file" class="input input-sm" accept=".txt,.csv,.list"></label>
      </div>
      <textarea name="text" class="textarea mono" rows="4" placeholder="One domain per line"></textarea>
      <div class="row"><button type="submit" class="btn btn-sm btn-solid">Import</button><button type="button" class="btn btn-sm btn-quiet" @click="importOpen = false">Cancel</button></div>
    </form>
    <section class="panel"><div class="table-wrap"><table class="tbl">
      <thead><tr><th>Site</th><th>Type</th><th>Source</th><th class="right">Blocked</th></tr></thead>
      <tbody><template x-for="s in shown" :key="s.id"><tr :style="s.off && 'opacity:.5'">
        <td class="mono" x-text="s.d"></td><td><span class="chip" :class="s.c === 'ai' && 'alert'" x-text="lab(s.c)"></span></td><td class="muted" x-text="s.s"></td>
        <td class="right nw">
          <button type="button" class="btn btn-sm btn-quiet" x-show="s.s !== 'built-in'" @click="deleteSite(s)" title="Remove entry" style="margin-right:8px"><svg class="i i-sm" aria-hidden="true"><use href="#i-trash"/></svg></button>
          <label class="switch" style="vertical-align:middle"><input type="checkbox" :checked="!s.off" @change="toggleSite(s)" :aria-label="'Block ' + s.d"><i></i></label>
        </td></tr></template>
        <template x-if="!shown.length"><tr><td colspan="4" class="muted" style="padding:18px 16px">No blocklist domains match this filter.</td></tr></template>
      </tbody>
    </table></div><div class="tbl-foot">
      <span>@if(isset($entries) && $entries->total() > 0) Showing {{ $entries->firstItem() }}–{{ $entries->lastItem() }} of {{ $entries->total() }} sites · @endif Changes apply to PCs within seconds.</span>
      @if(isset($entries) && $entries->hasPages())
        <div class="pager">
          @if($entries->onFirstPage())
            <button disabled>Prev</button>
          @else
            <a class="btn btn-sm" href="{{ $entries->previousPageUrl() }}">Prev</a>
          @endif
          @if($entries->hasMorePages())
            <a class="btn btn-sm" href="{{ $entries->nextPageUrl() }}">Next</a>
          @else
            <button disabled>Next</button>
          @endif
        </div>
      @endif
    </div></section>
  </section>

  <section x-show="tab === 'rules'" x-cloak>
    <div class="toolbar">
      <div class="pills"><template x-for="k in kinds" :key="k"><button class="pill" :aria-pressed="rk === k" @click="rk = k" style="text-transform:capitalize" x-text="k"></button></template></div>
      <span class="grow"></span>
      <input class="input input-sm" style="width:220px" placeholder="Search rules" x-model="rq">
      <button type="button" class="btn btn-sm btn-solid" @click="openRuleModal(null)"><svg class="i i-sm" aria-hidden="true"><use href="#i-plus"/></svg> Add rule</button>
    </div>
    <section class="panel"><div class="table-wrap"><table class="tbl">
      <thead><tr><th>Rule</th><th>Severity</th><th>What it catches</th><th class="right">Enabled</th></tr></thead>
      <tbody><template x-for="r in rshown" :key="r.id"><tr :style="!r.on && 'opacity:.5'"><td><div class="mono" style="font-weight:500" x-text="r.id"></div><div class="tiny muted" style="text-transform:capitalize" x-text="r.kind"></div></td><td><span class="sev" :class="r.sev" x-text="r.sev"></span></td><td x-text="r.desc"></td><td class="right nw"><button type="button" class="btn btn-sm btn-quiet" @click="openRuleModal(r)" style="margin-right:8px">Edit</button><label class="switch" style="vertical-align:middle"><input type="checkbox" x-model="r.on" @change="toggleRule(r)" :aria-label="'Enable ' + r.id"><i></i></label></td></tr></template>
        <template x-if="!rshown.length"><tr><td colspan="4" class="muted" style="padding:18px 16px">No detection rules match this filter.</td></tr></template>
      </tbody>
    </table></div><div class="tbl-foot">Showing <span x-text="rshown.length"></span> of <span x-text="rules.length"></span> rules</div></section>
  </section>

  <section x-show="tab === 'versions'" x-cloak>
    <form method="post" action="{{ route('signatures.publish') }}" class="panel panel-pad stack" style="max-width:none" @submit="confirmSubmit($event, 'Publish to all PCs?')">
      @csrf
      <div><h2 class="h2">Publish the current rules</h2><p class="muted small" style="margin-top:2px">Signs the blocklists and rules and sends them to every PC.</p></div>
      <div class="row"><input name="note" class="input" style="max-width:420px" placeholder="What changed? (optional)"><button type="submit" class="btn btn-solid">Publish to PCs</button></div>
    </form>
    <section class="panel"><table class="tbl"><thead><tr><th>Version</th><th>Note</th><th>Published</th><th></th></tr></thead><tbody>
      <template x-for="v in versions" :key="v.v"><tr><td class="mono small" style="font-weight:500" x-text="v.v"></td><td x-text="v.note"></td><td class="muted" x-text="v.when"></td><td class="right">
        <span class="chip ok" x-show="v.active">In use</span>
        <form x-show="!v.active && v.id" method="post" :action="'/signatures/' + v.id + '/activate'" style="display:inline" @submit="confirmSubmit($event, 'Roll every PC back to this version?')">
          @csrf
          <button type="submit" class="btn btn-sm">Roll back</button>
        </form>
      </td></tr></template>
      <template x-if="!versions.length"><tr><td colspan="4" class="muted" style="padding:18px 16px">No published signature versions yet.</td></tr></template>
    </tbody></table></section>
  </section>

  <!-- Add / Edit Rule Modal -->
  <div class="overlay" x-show="ruleModal" x-cloak x-transition.opacity @click.self="ruleModal = false">
    <div class="modal" style="width:min(540px,100%)" role="dialog" aria-label="Detection rule">
      <div class="modal-head"><span class="h2">Detection rule</span><button class="xbtn" @click="ruleModal = false" aria-label="Close"><svg class="i" aria-hidden="true"><use href="#i-x"/></svg></button></div>
      <form method="post" action="{{ route('rules.save') }}">
        @csrf
        <input type="hidden" name="enabled" value="1">
        <div class="modal-body stack">
          <div class="form-grid">
            <label class="field"><span>Rule ID</span><input name="rule_id" class="input mono" x-model="ruleForm.rule_id" placeholder="proc.ollama" required></label>
            <label class="field"><span>Kind</span>
              <select name="kind" class="select" x-model="ruleForm.kind">
                <option value="process">Process</option>
                <option value="extension">Extension</option>
                <option value="port">Listening port</option>
                <option value="artifact">Local AI file</option>
                <option value="adapter">Network adapter</option>
                <option value="device">USB device</option>
              </select>
            </label>
          </div>
          <div class="form-grid">
            <label class="field"><span>Severity</span>
              <select name="severity" class="select" x-model="ruleForm.severity">
                <option value="info">Info</option>
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </label>
            <label class="field"><span>Description</span><input name="description" class="input" x-model="ruleForm.description" placeholder="What it catches"></label>
          </div>
          <label class="field"><span>Definition (JSON)</span><textarea name="definition" class="textarea mono" rows="4" x-model="ruleForm.definition" required></textarea></label>
          <div>
            <span class="label">Actions in Test / Exam mode</span>
            <div class="checks-grid">
              <template x-for="act in ['log','warn','kill','alert','isolate']" :key="act">
                <label class="check"><input type="checkbox" name="test_actions[]" :value="act" :checked="ruleForm.actions.includes(act)" @change="flipAction(act)"> <span style="text-transform:capitalize" x-text="act"></span></label>
              </template>
            </div>
          </div>
        </div>
        <div class="modal-foot"><button type="button" class="btn" @click="ruleModal = false">Cancel</button><button type="submit" class="btn btn-solid">Save rule</button></div>
      </form>
    </div>
  </div>
</div></div>
@endsection
