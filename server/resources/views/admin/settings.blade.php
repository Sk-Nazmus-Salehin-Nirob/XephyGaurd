@extends('layouts.app', ['activePage' => 'settings.html'])
@section('title', 'Settings')
@section('content')
<div class="doc" x-data="{ cur: 'network', mode: 'proxy', pasteAt: 800, tAlways: 'off', tPractice: 'app', tTest: 'full', hosts: true, queries: false,
  go(id) { this.cur = id; document.getElementById(id).scrollIntoView({ behavior: 'smooth', block: 'start' }); } }"><div class="optbar"><span class="otitle">Settings</span><span class="osub">Network, privacy and the notice students see.</span><span class="grow"></span></div><div class="canvas ">
  
  <div class="cols-side" style="grid-template-columns:200px minmax(0,1fr)">
    <nav class="index" aria-label="Sections">
      <a href="#network" :class="cur === 'network' && 'on'" @click.prevent="go('network')">Network</a>
      <a href="#search" :class="cur === 'search' && 'on'" @click.prevent="go('search')">Search AI summaries</a>
      <a href="#privacy" :class="cur === 'privacy' && 'on'" @click.prevent="go('privacy')">Privacy and retention</a>
      <a href="#notice" :class="cur === 'notice' && 'on'" @click.prevent="go('notice')">Student notice</a>
    </nav>
    <form @submit.prevent="$store.toasts.add('Settings saved.', 'ok')">
      <section class="section" id="network"><div class="panel-head"><h2 class="h2">Network</h2></div>
        <div class="panel-body stack" style="max-width:760px;--gap:20px">
          <div class="form-grid"><label class="field"><span>Lab name</span><input class="input" value="KUET CSE Computer Lab 1"></label>
            <label class="field"><span>Time zone</span><select class="select"><option selected>Asia/Dhaka</option><option>UTC</option></select></label></div>
          <div><div class="label">How traffic reaches this server</div><div class="stack" style="--gap:8px">
            <label class="opt"><input type="radio" name="mode" value="gateway" x-model="mode"><span><b>Gateway mode</b><small>This server is the lab’s default gateway. Students can’t get around blocking with browser proxy settings.</small></span></label>
            <label class="opt"><input type="radio" name="mode" value="proxy" x-model="mode"><span><b>Proxy only</b><small>The router sends web traffic here. Easier to set up, easier to get around.</small></span></label></div></div>
          <div class="form-grid"><label class="field"><span>Server address</span><input class="input mono" value="192.168.0.51"></label><label class="field"><span>Lab subnet</span><input class="input mono" value="192.168.0.0/24"></label></div>
        </div></section>
      <section class="section" id="search"><div class="panel-head"><h2 class="h2">Search AI summaries</h2></div>
        <div class="panel-body stack" style="max-width:760px;--gap:18px">
          <label class="field"><span>Search sites to inspect</span><textarea class="textarea mono" rows="3">www.google.com
search.yahoo.com
duckduckgo.com</textarea><p class="help">Only these sites are opened up so AI summary boxes can be hidden.</p></label>
          <label class="field"><span>Selectors that hide AI summaries</span><textarea class="textarea mono" rows="2">div[data-attrid="AIOverview"], #m-x-content, g-ai-overview</textarea></label>
          <label class="field" style="max-width:260px"><span>Alert on pastes over (characters)</span><input class="input" type="number" x-model.number="pasteAt"></label>
        </div></section>
      <section class="section" id="privacy"><div class="panel-head"><h2 class="h2">Privacy and retention</h2></div>
        <div class="panel-body stack" style="max-width:760px;--gap:20px">
          <div class="form-grid"><label class="field"><span>Keep raw activity for (days)</span><input class="input" type="number" value="140"></label><label class="field"><span>Keep finished reports for (days)</span><input class="input" type="number" value="1825"></label></div>
          <div><div class="label">Window titles</div>
            <table class="tbl tight" style="max-width:560px;border:1px solid var(--border);border-radius:8px"><tbody>
              <tr><td>Outside class</td><td class="right"><div class="seg"><button type="button" :aria-pressed="tAlways === 'off'" @click="tAlways = 'off'">Off</button><button type="button" :aria-pressed="tAlways === 'app'" @click="tAlways = 'app'">Program</button><button type="button" :aria-pressed="tAlways === 'full'" @click="tAlways = 'full'">Full</button></div></td></tr>
              <tr><td>Practice class</td><td class="right"><div class="seg"><button type="button" :aria-pressed="tPractice === 'off'" @click="tPractice = 'off'">Off</button><button type="button" :aria-pressed="tPractice === 'app'" @click="tPractice = 'app'">Program</button><button type="button" :aria-pressed="tPractice === 'full'" @click="tPractice = 'full'">Full</button></div></td></tr>
              <tr><td>Test or exam</td><td class="right"><div class="seg"><button type="button" :aria-pressed="tTest === 'off'" @click="tTest = 'off'">Off</button><button type="button" :aria-pressed="tTest === 'app'" @click="tTest = 'app'">Program</button><button type="button" :aria-pressed="tTest === 'full'" @click="tTest = 'full'">Full</button></div></td></tr></tbody></table></div>
          <div class="stack" style="--gap:12px"><label class="check"><span class="switch"><input type="checkbox" x-model="hosts"><i></i></span> Log which allowed sites are visited</label><label class="check" x-show="hosts"><span class="switch"><input type="checkbox" x-model="queries"><i></i></span> <span>Include search terms <span class="muted">(off by default)</span></span></label></div>
        </div></section>
      <section class="section" id="notice"><div class="panel-head"><h2 class="h2">Student notice</h2><a class="small" href="notice.html">Preview</a></div>
        <div class="panel-body" style="max-width:760px"><textarea class="textarea" rows="4">Lab computers are equipped with XephyGuard. During tests, generative AI and assistance tools are blocked. Passwords and typed text are never collected. Screens are viewed only by your instructor, only during a session, and a notice is shown on your screen while it happens.</textarea><p class="help">Shown on the agent’s indicator and on the public notice page.</p></div></section>
      <div class="savebar"><span class="muted small grow">Changes apply to every PC within a few seconds.</span><button type="button" class="btn">Discard</button><button class="btn btn-solid">Save settings</button></div>
    </form>
  </div>
</div></div>
@endsection