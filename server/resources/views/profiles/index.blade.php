@extends('layouts.app', ['activePage' => 'profiles.html'])
@section('title', 'Timetable and profiles')
@section('content')
<div class="doc" x-data="{
  tab: 'profiles', cur: 3, hr: 44, start: 8, end: 18, days: ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'], addOpen: false,
  profiles: [
    { name: 'Always-on', mode: 'always', desc: 'Quiet safety net outside class. Nothing is blocked.', block: [], strict: false, aiov: false, collect: ['artifacts'], titles: 'off', kill: 'proc.ollama\nproc.llamacpp' },
    { name: 'Practice: AI allowed', mode: 'practice', desc: 'Normal class. AI is reachable and use is recorded.', block: [], strict: false, aiov: false, collect: ['window', 'clipboard', 'keys', 'artifacts'], titles: 'app', kill: '' },
    { name: 'Practice: AI blocked', mode: 'practice', desc: 'Docs stay open. AI chat sites and assistants are blocked.', block: ['ai', 'ide', 'doh'], strict: false, aiov: true, collect: ['window', 'clipboard', 'keys', 'artifacts'], titles: 'app', kill: 'proc.ollama' },
    { name: 'Test: AI blocked', mode: 'test', desc: 'Full AI blocklist, assistant suppression and strict outbound rules.', block: ['ai', 'ide', 'marketplace', 'vpn', 'doh'], strict: true, aiov: true, collect: ['window', 'clipboard', 'keys', 'files', 'artifacts'], titles: 'full', kill: 'proc.ollama\nproc.llamacpp\nproc.lmstudio' },
    { name: 'Exam: strict', mode: 'exam', desc: 'Everything in Test, plus kiosk mode and an allow-list only.', block: ['ai', 'ide', 'marketplace', 'vpn', 'doh', 'custom'], strict: true, aiov: true, collect: ['window', 'clipboard', 'keys', 'files', 'gpu', 'artifacts'], titles: 'full', kill: 'proc.ollama\nproc.llamacpp\nproc.lmstudio' }
  ],
  cats: [['ai', 'AI chat sites'], ['ide', 'Editor assistants'], ['marketplace', 'Code marketplaces'], ['vpn', 'VPNs and proxies'], ['doh', 'Encrypted DNS'], ['custom', 'Custom list']],
  coll: [['window', 'Active window'], ['clipboard', 'Paste size'], ['keys', 'Typing pace'], ['files', 'File activity'], ['gpu', 'GPU use'], ['artifacts', 'Installed AI files']],
  get p() { return this.profiles[this.cur]; },
  has(arr, k) { return arr.includes(k); },
  flip(arr, k) { const i = arr.indexOf(k); i >= 0 ? arr.splice(i, 1) : arr.push(k); },
  items: [
    { id: 1, day: 'Sun', from: '09:00', to: '11:00', course: 'CSE 2102', profile: 'Practice: AI allowed', paused: false },
    { id: 2, day: 'Tue', from: '11:00', to: '13:00', course: 'CSER', profile: 'Exam: strict', paused: false }
  ],
  form: { day: 'Sun', from: '09:00', to: '11:00', course: '', profile: 'Test: AI blocked' },
  modeOf(p) { return p.startsWith('Test') ? 'test' : p.startsWith('Exam') ? 'exam' : p.startsWith('Practice') ? 'practice' : 'always'; },
  top(t) { const [h, m] = t.split(':'); return ((+h - this.start) + (+m) / 60) * this.hr; },
  tall(i) { return Math.max(28, this.top(i.to) - this.top(i.from)); },
  add() { if (!this.form.course.trim()) return; this.items.push({ id: Date.now(), ...this.form, paused: false }); this.form.course = ''; this.addOpen = false; $store.toasts.add('Added to the timetable.', 'ok'); }
}"><div class="optbar"><span class="otitle">Timetable and profiles</span><span class="osub">What each class runs under, and when.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="tabs" role="tablist"><button role="tab" :aria-selected="tab === 'profiles'" @click="tab = 'profiles'">Profiles</button><button role="tab" :aria-selected="tab === 'timetable'" @click="tab = 'timetable'">Timetable</button></div>

  <!-- Profiles -->
  <div x-show="tab === 'profiles'" class="cols-side" style="grid-template-columns:300px minmax(0,1fr)">
    <div class="panel" style="min-height:100%">
      <ul class="plist"><template x-for="(pr, i) in profiles" :key="pr.name"><li :class="cur === i && 'on'" @click="cur = i"><div class="grow" style="min-width:0"><div class="t" x-text="pr.name"></div><div class="d" x-text="pr.desc"></div></div><span class="mode" :class="pr.mode" x-text="pr.mode === 'always' ? 'Always' : pr.mode" style="text-transform:capitalize"></span></li></template></ul>
    </div>
    <form @submit.prevent="$store.toasts.add('Profile saved. It applies to the next session.', 'ok')">
      <section class="panel panel-pad" style="padding:20px 24px">
        <div class="fgroup stack">
          <h2 class="h2">General</h2>
          <div class="form-grid"><label class="field"><span>Name</span><input class="input" x-model="p.name"></label>
            <label class="field"><span>Type</span><select class="select" x-model="p.mode"><option value="always">Always-on</option><option value="practice">Practice</option><option value="test">Test</option><option value="exam">Exam</option></select></label></div>
          <label class="field"><span>Description</span><input class="input" x-model="p.desc"></label>
        </div>
        <div class="fgroup stack">
          <div><h2 class="h2">Blocking</h2><p class="muted small">Which kinds of sites are cut off during this profile.</p></div>
          <div class="checks-grid"><template x-for="c in cats" :key="c[0]"><label class="check"><input type="checkbox" :checked="has(p.block, c[0])" @change="flip(p.block, c[0])"> <span x-text="c[1]"></span></label></template></div>
          <label class="check"><span class="switch"><input type="checkbox" x-model="p.strict"><i></i></span> Strict outbound: only approved destinations</label>
          <label class="check"><span class="switch"><input type="checkbox" x-model="p.aiov"><i></i></span> Hide AI summaries in search results</label>
        </div>
        <div class="fgroup stack">
          <div><h2 class="h2">What the agent notices</h2><p class="muted small">Keys pressed and pasted text are never collected.</p></div>
          <div class="checks-grid"><template x-for="c in coll" :key="c[0]"><label class="check"><input type="checkbox" :checked="has(p.collect, c[0])" @change="flip(p.collect, c[0])"> <span x-text="c[1]"></span></label></template></div>
          <label class="field" style="max-width:260px"><span>Window titles</span><select class="select" x-model="p.titles"><option value="off">Not recorded</option><option value="app">Program name only</option><option value="full">Full title</option></select></label>
        </div>
        <div class="fgroup stack">
          <div><h2 class="h2">Close automatically</h2><p class="muted small">Detection rule IDs, one per line. Matching programs are closed on sight.</p></div>
          <textarea class="textarea mono" rows="3" x-model="p.kill" placeholder="proc.ollama"></textarea>
        </div>
      </section>
      <div class="savebar"><span class="muted small grow">Changes apply to the next session that uses this profile.</span><button type="button" class="btn">Discard</button><button class="btn btn-solid">Save profile</button></div>
    </form>
  </div>

  <!-- Timetable -->
  <div x-show="tab === 'timetable'" x-cloak class="cols-main" style="grid-template-columns:minmax(0,1fr) 380px">
    <section class="panel panel-pad">
      <div class="row" style="margin-bottom:14px"><h2 class="h2 grow">This week</h2><button class="btn btn-solid btn-sm" @click="addOpen = !addOpen"><svg class="i i-sm" aria-hidden="true"><use href="#i-plus"/></svg> Add a class</button></div>
      <div class="week" :style="'--hr:' + hr">
        <div class="hd"></div><template x-for="d in days" :key="'h' + d"><div class="hd" x-text="d"></div></template>
        <div class="hours" :style="'height:' + ((end - start) * hr) + 'px'"><template x-for="h in (end - start)" :key="'t' + h"><span :style="'top:' + ((h - 1) * hr) + 'px'" x-text="String(start + h - 1).padStart(2, '0')"></span></template></div>
        <template x-for="d in days" :key="'c' + d"><div class="daycol" :style="'height:' + ((end - start) * hr) + 'px'"><template x-for="i in items.filter(x => x.day === d)" :key="i.id"><div class="slot" :class="['m-' + modeOf(i.profile), i.paused ? 'paused' : '']" :style="'top:' + top(i.from) + 'px;height:' + tall(i) + 'px'"><b x-text="i.course"></b><span x-text="i.from + '–' + i.to"></span></div></template></div></template>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h2 class="h2">Schedule</h2></div>
      <template x-for="i in items" :key="i.id"><div class="row" style="padding:12px 20px;border-bottom:1px solid var(--border);flex-wrap:nowrap" :style="i.paused && 'opacity:.55'"><div class="grow"><div style="font-weight:500" x-text="i.course"></div><div class="small muted" x-text="i.day + ' ' + i.from + '–' + i.to + ' · ' + i.profile"></div></div><button class="btn btn-sm btn-quiet" @click="i.paused = !i.paused" x-text="i.paused ? 'Resume' : 'Pause'"></button><button class="btn btn-sm btn-quiet" @click="items = items.filter(x => x.id !== i.id)" aria-label="Remove"><svg class="i i-sm" aria-hidden="true"><use href="#i-trash"/></svg></button></div></template>
      <div class="empty-state" x-show="!items.length"><b>No classes yet</b>Add one to start sessions automatically.</div>
      <form x-show="addOpen" x-cloak class="panel-body stack" style="background:var(--surface-2);border-top:1px solid var(--border)" @submit.prevent="add()">
        <div class="form-grid"><label class="field"><span>Day</span><select class="select" x-model="form.day"><template x-for="d in days"><option x-text="d"></option></template></select></label><label class="field"><span>Course</span><input class="input" x-model="form.course" required></label>
        <label class="field"><span>Starts</span><input class="input" type="time" x-model="form.from"></label><label class="field"><span>Ends</span><input class="input" type="time" x-model="form.to"></label></div>
        <label class="field"><span>Profile</span><select class="select" x-model="form.profile"><template x-for="pr in profiles" :key="pr.name"><option x-text="pr.name"></option></template></select></label>
        <div class="row"><button class="btn btn-solid">Add</button><button type="button" class="btn btn-quiet" @click="addOpen = false">Cancel</button></div>
      </form>
    </section>
  </div>
</div></div>
@endsection
