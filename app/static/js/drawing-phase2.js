/* ============================================================
   QUOTING STUDIO — DRAWING ENGINE PHASE 2
   Openers · Profiles · Frame · Finish · Glass  (modal dialogs)

   Attaches to window.QSDraw and the editor's global `model`, `dc`.
   Framepoint-style modals matching the reference screenshots.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- catalog data ---------- */
  const OPENING_TYPES = [
    'Fixed','Sliding','Left Open','Right Open','Top Hung',
    'Bottom Hung','Tilt','Tilt & Turn','French','Casement'
  ];

  // RAL colour catalog (matches the Framepoint "Manage Frame Finish" grid)
  const FINISH_COLOURS = [
    { name:'Agate Grey',      ral:'RAL 7038', hex:'#B4B8B0' },
    { name:'Anthracite Grey', ral:'RAL 7016', hex:'#2B2F33' },
    { name:'Black Brown',     ral:'RAL 8022', hex:'#241E1C' },
    { name:'Cream',           ral:'RAL 9001', hex:'#EFE9D8' },
    { name:'Jet Black',       ral:'RAL 9005', hex:'#0A0A0A' },
    { name:'Light Ivory',     ral:'RAL 1015', hex:'#E6D2A8' },
    { name:'White',           ral:'RAL 9016', hex:'#F1F0EA' },
    { name:'Slate Grey',      ral:'RAL 7015', hex:'#4E5157' },
    { name:'Chartwell Green', ral:'RAL 6019', hex:'#A8C6A0' },
    { name:'Fir Green',       ral:'RAL 6009', hex:'#27352A' },
    { name:'Steel Blue',      ral:'RAL 5011', hex:'#1F3547' },
    { name:'Bronze',          ral:'RAL 8019', hex:'#3D3635' },
  ];

  const FINISH_TYPES = ['Paints','Woodgrain','Metallic','Standard'];
  const FINISH_BASES = ['Smooth','Woodgrain','Textured'];

  // Glass sealed units (matches "Choose a Standard Sealed Unit")
  const GLASS_UNITS = [
    { name:"A' Rated 4-20-4 Clear Argon",              spec:'Double, Low-E', std:true },
    { name:'4-16-4 Clear Toughened',                   spec:'Double, Low-E', std:true },
    { name:'4-20-4 Low Iron Soft Clear Tough Argon',   spec:'Double, Low-E', std:false },
    { name:'4-20-4 Soft 1.0 Low Iron Clear Tough Argon',spec:'Double, Low-E',std:false },
    { name:'Triple 4-12-4-12-4 Argon',                 spec:'Triple glazed', std:true },
    { name:'6-16-6.8 Sun Cool 70/35 Tough Acoustic Argon', spec:'Acoustic', std:false, acoustic:true, solar:true },
    { name:'6-18-4 Sun Cool 70/35 Tough Argon',        spec:'Solar control', std:false, solar:true },
    { name:'6.8 Acoustic Laminate',                    spec:'Acoustic', std:false, acoustic:true },
    { name:'Obscure Level 3',                          spec:'Obscure', std:true },
    { name:'Solar Control Neutral',                    spec:'Solar control', std:false, solar:true },
  ];
  const GLASS_TEXTURES = ['None','Clear','Obscure Lvl 3','Obscure Lvl 5','Stippolyte','Cotswold'];
  const SPACER_BARS    = ['Warm Edge Black','Warm Edge White','Aluminium Silver','Anthracite'];

  /* ---------- modal shell ---------- */
  function modal(title, bodyHTML, footerHTML) {
    closeModal();
    const back = document.createElement('div');
    back.className = 'p2-modal-back';
    back.id = 'p2modal';
    back.innerHTML = `
      <div class="p2-modal">
        <div class="p2-modal-head">
          <h3>${title}</h3>
          <button class="p2-x" onclick="QSPhase2.close()">✕</button>
        </div>
        <div class="p2-modal-body">${bodyHTML}</div>
        <div class="p2-modal-foot">${footerHTML}</div>
      </div>`;
    back.addEventListener('mousedown', e => { if (e.target === back) closeModal(); });
    document.body.appendChild(back);
    requestAnimationFrame(() => back.classList.add('show'));
    return back;
  }
  function closeModal() {
    const m = document.getElementById('p2modal');
    if (m) m.remove();
  }

  function selectedPane() {
    return window.model.panes.find(p => p.id === window.dc.selectedPaneId)
        || window.model.panes[0];
  }
  function commit() {
    window.dc.render();
    if (window.scheduleSave) window.scheduleSave();
    if (window.fetchPricing) window.fetchPricing();
    if (window.renderTab)   window.renderTab();
  }

  /* ============================================================
     1. OPENERS MODAL
     ============================================================ */
  function openOpeners() {
    const pane = selectedPane();
    const cur  = pane ? pane.opening : 'Fixed';
    const cards = OPENING_TYPES.map(t => `
      <div class="p2-open-card ${t===cur?'sel':''}" data-open="${t}"
           onclick="QSPhase2._pickOpen('${t}')">
        <div class="p2-open-vis">${openerSVG(t)}</div>
        <div class="p2-open-lbl">${t}</div>
      </div>`).join('');
    modal(
      `Openers at ${pane ? 'selected pane' : 'pane'}`,
      `<div class="p2-open-grid">${cards}</div>`,
      `<button class="p2-btn ghost" onclick="QSPhase2.close()">Close</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyOpen('pane')">Apply</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyOpen('all')">Apply to All</button>`
    );
  }
  let _pendingOpen = null;
  function _pickOpen(t) {
    _pendingOpen = t;
    document.querySelectorAll('.p2-open-card').forEach(c =>
      c.classList.toggle('sel', c.dataset.open === t));
  }
  function _applyOpen(scope) {
    const t = _pendingOpen || selectedPane().opening;
    if (scope === 'all') window.model.panes.forEach(p => p.opening = t);
    else selectedPane().opening = t;
    _pendingOpen = null;
    commit(); closeModal();
  }

  function openerSVG(t) {
    const v = 'stroke="#6b7a90" stroke-width="2" fill="none" stroke-dasharray="4,3"';
    let inner = '';
    if (t.includes('Top')||t==='Bottom Hung') inner=`<line x1="6" y1="46" x2="30" y2="26" ${v}/><line x1="54" y1="46" x2="30" y2="26" ${v}/>`;
    else if (t.includes('Left')||t==='Casement') inner=`<line x1="6" y1="6" x2="30" y2="26" ${v}/><line x1="6" y1="46" x2="30" y2="26" ${v}/>`;
    else if (t.includes('Right')) inner=`<line x1="54" y1="6" x2="30" y2="26" ${v}/><line x1="54" y1="46" x2="30" y2="26" ${v}/>`;
    else if (t.includes('Tilt')) inner=`<line x1="6" y1="46" x2="30" y2="26" ${v}/><line x1="54" y1="46" x2="30" y2="26" ${v}/><line x1="6" y1="6" x2="30" y2="26" ${v}/>`;
    else if (t.includes('Slid')||t==='French') inner=`<line x1="6" y1="26" x2="54" y2="26" ${v}/><polyline points="24,20 18,26 24,32" ${v}/>`;
    return `<svg viewBox="0 0 60 52"><rect x="4" y="4" width="52" height="44" fill="url(#glass)" stroke="#9fb4bd" stroke-width="1.5"/>${inner}</svg>`;
  }

  /* ============================================================
     2. PROFILE MODAL  (Frame / Sash / Sash Horns tabs)
     ============================================================ */
  function openProfile() {
    const f = window.model.frame;
    modal(
      'Manage Frame Profiles',
      `<div class="p2-tabs">
         <div class="p2-tab on" data-t="frame" onclick="QSPhase2._profTab('frame')">FRAME</div>
         <div class="p2-tab" data-t="sash" onclick="QSPhase2._profTab('sash')">SASH</div>
         <div class="p2-tab" data-t="horns" onclick="QSPhase2._profTab('horns')">SASH HORNS</div>
       </div>
       <div id="p2profBody" class="p2-prof-body"></div>`,
      `<button class="p2-btn primary" onclick="QSPhase2.close()">Close</button>`
    );
    _profTab('frame');
  }
  function _profTab(t) {
    document.querySelectorAll('#p2modal .p2-tab').forEach(el =>
      el.classList.toggle('on', el.dataset.t === t));
    const f = window.model.frame;
    const body = document.getElementById('p2profBody');
    const toggle = (id, label, on) => `
      <div class="p2-toggle-row">
        <label class="p2-switch"><input type="checkbox" id="${id}" ${on?'checked':''}
          onchange="QSPhase2._profToggle('${id}')"><span class="p2-slider"></span></label>
        <label for="${id}">${label}</label>
      </div>`;
    if (t === 'frame') {
      body.innerHTML =
        toggle('p2SlimClip','Slim Mullion Clip', f.slimMullionClip) +
        toggle('p2StaffBead','Staff Bead', f.staffBead) +
        `<div class="p2-field"><label>Outer profile</label>
          <select id="outerProf" onchange="QSPhase2._profSelect('outerProfile','outerProf')">
            ${['Standard','Chamfered','Ovolo','Sculptured'].map(o=>`<option ${f.outerProfile===o?'selected':''}>${o}</option>`).join('')}
          </select></div>`;
    } else if (t === 'sash') {
      body.innerHTML =
        `<div class="p2-field"><label>Sash profile</label>
          <select id="innerProf" onchange="QSPhase2._profSelect('innerProfile','innerProf')">
            ${['Standard','Slim','Heritage','Flush'].map(o=>`<option ${f.innerProfile===o?'selected':''}>${o}</option>`).join('')}
          </select></div>` +
        toggle('flushSash','Flush casement', f.flushSash);
    } else {
      body.innerHTML =
        toggle('sashHorns','Sash horns', f.sashHorns) +
        `<div class="p2-note">Traditional sash horns add a period detail to the top sash.</div>`;
    }
  }
  function _profToggle(id) {
    const el = document.getElementById(id); if (!el) return;
    const map = {p2SlimClip:'slimMullionClip', p2StaffBead:'staffBead',
                 flushSash:'flushSash', sashHorns:'sashHorns'};
    window.model.frame[map[id]] = el.checked;
    commit();
    // keep the sidebar's Slim Mullion Clip / Staff Bead checkboxes
    // (rendered on the Frame Settings tab, separate ids) in sync
    const sideSlim  = document.getElementById('slimClip');
    const sideStaff = document.getElementById('staffBead');
    if (sideSlim)  sideSlim.checked  = window.model.frame.slimMullionClip;
    if (sideStaff) sideStaff.checked = window.model.frame.staffBead;
  }
  function _profSelect(key, id) {
    window.model.frame[key] = document.getElementById(id).value;
    commit();
  }

  /* ============================================================
     3. FINISH MODAL  (Frame / Sash / Cill tabs + colour grid)
     ============================================================ */
  let _finishTarget = 'frame';
  function _finishKey(t) {
    return t === 'frame' ? 'color'
         : t === 'sash'  ? 'sashColor'
         : 'cillColor';
  }
  function openFinish() {
    _finishTarget = 'frame';
    modal(
      'Manage Frame Finish',
      `<div class="p2-tabs">
         <div class="p2-tab on" data-t="frame" onclick="QSPhase2._finishTab('frame')">FRAME</div>
         <div class="p2-tab" data-t="sash" onclick="QSPhase2._finishTab('sash')">SASH</div>
         <div class="p2-tab" data-t="cill" onclick="QSPhase2._finishTab('cill')">CILL</div>
       </div>
       <div class="p2-finish-controls">
         <div class="p2-field inline"><label>Type</label>
           <select id="finType">${FINISH_TYPES.map(x=>`<option>${x}</option>`).join('')}</select></div>
         <div class="p2-field inline"><label>Base</label>
           <select id="finBase">${FINISH_BASES.map(x=>`<option>${x}</option>`).join('')}</select></div>
       </div>
       <div class="p2-toggle-row" style="margin:6px 0 14px;">
         <label class="p2-switch"><input type="checkbox" id="sameBoth" checked><span class="p2-slider"></span></label>
         <label for="sameBoth">Same Finish on Both Sides: <strong id="sameBothLbl">Yes</strong></label>
       </div>
       <div class="p2-colour-grid" id="p2colourGrid"></div>`,
      `<button class="p2-btn ghost" onclick="QSPhase2.close()">Close</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyFinish('frame')">Apply to Frame</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyFinish('all')">Apply to All</button>`
    );
    document.getElementById('sameBoth').addEventListener('change', function(){
      document.getElementById('sameBothLbl').textContent = this.checked ? 'Yes' : 'No';
    });
    _buildColourGrid();
  }
  // pendingFinish is pre-seeded with the current colour for each part so
  // Apply works immediately even if the user doesn't click a new swatch.
  let _pendingFinish = null;
  function _finishTab(t) {
    _finishTarget = t;
    document.querySelectorAll('#p2modal .p2-tab').forEach(el =>
      el.classList.toggle('on', el.dataset.t === t));
    _buildColourGrid();
  }
  function _buildColourGrid() {
    const grid = document.getElementById('p2colourGrid');
    const key = _finishKey(_finishTarget);
    const cur = window.model.frame[key] || window.model.frame.color;
    const curEntry = FINISH_COLOURS.find(c => c.hex === cur) || FINISH_COLOURS[0];
    _pendingFinish = { hex: curEntry.hex, name: curEntry.name, ral: curEntry.ral };
    grid.innerHTML = FINISH_COLOURS.map(c => `
      <div class="p2-colour-card ${c.hex===curEntry.hex?'sel':''}" data-hex="${c.hex}"
           onclick="QSPhase2._pickFinish('${c.hex}','${c.name}','${c.ral}')">
        <div class="p2-colour-sw" style="background:${c.hex}"></div>
        <div class="p2-colour-nm">${c.name}</div>
        <div class="p2-colour-ral">${c.ral}</div>
      </div>`).join('');
  }
  function _pickFinish(hex, name, ral) {
    _pendingFinish = { hex, name, ral };
    document.querySelectorAll('.p2-colour-card').forEach(c =>
      c.classList.toggle('sel', c.dataset.hex === hex));
  }
  function _applyFinish(scope) {
    const f = _pendingFinish;
    if (!f) { closeModal(); return; }
    if (scope === 'all') {
      window.model.frame.color = f.hex;
      window.model.frame.colorName = f.name;
      window.model.frame.ral = f.ral;
      window.model.frame.sashColor = f.hex;
      window.model.frame.sashColorName = f.name;
      window.model.frame.cillColor = f.hex;
      window.model.frame.cillColorName = f.name;
    } else {
      const key = _finishKey(_finishTarget);
      window.model.frame[key] = f.hex;
      window.model.frame[key + 'Name'] = f.name;
      if (_finishTarget === 'frame') window.model.frame.ral = f.ral;
    }
    _pendingFinish = null;
    commit(); closeModal();
  }

  /* ============================================================
     4. GLASS MODAL  (Panes / Textures / Spacer Bars tabs)
     ============================================================ */
  function openGlass() {
    const pane = selectedPane();
    modal(
      `Glass at ${pane ? 'selected pane' : 'pane'}`,
      `<div class="p2-tabs">
         <div class="p2-tab on" data-t="panes" onclick="QSPhase2._glassTab('panes')">PANES</div>
         <div class="p2-tab" data-t="tex" onclick="QSPhase2._glassTab('tex')">TEXTURES</div>
         <div class="p2-tab" data-t="spacer" onclick="QSPhase2._glassTab('spacer')">SPACER BARS</div>
       </div>
       <div id="p2glassBody" class="p2-glass-body"></div>`,
      `<button class="p2-btn ghost" onclick="QSPhase2.close()">Done</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyGlass('pane')">Apply to Pane</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyGlass('selected')">Apply to Selected</button>
       <button class="p2-btn primary" onclick="QSPhase2._applyGlass('all')">Apply to All</button>`
    );
    _glassTab('panes');
  }
  let _pendingGlass = null, _pendingTex = null, _pendingSpacer = null;
  function _glassTab(t) {
    document.querySelectorAll('#p2modal .p2-tab').forEach(el =>
      el.classList.toggle('on', el.dataset.t === t));
    const body = document.getElementById('p2glassBody');
    const pane = selectedPane();
    if (t === 'panes') {
      _renderGlassPanes(pane);
    } else if (t === 'tex') {
      body.innerHTML =
        `<div class="p2-note">Glass texture / obscure level:</div>
         <div class="p2-field">
           <select id="glassTex" onchange="QSPhase2._pendTex()">
             ${GLASS_TEXTURES.map(x=>`<option ${pane&&pane.texture===x?'selected':''}>${x}</option>`).join('')}
           </select></div>`;
    } else {
      body.innerHTML =
        `<div class="p2-note">Spacer bar colour:</div>
         <div class="p2-field">
           <select id="glassSpacer" onchange="QSPhase2._pendSpacer()">
             ${SPACER_BARS.map(x=>`<option ${pane&&pane.spacer===x?'selected':''}>${x}</option>`).join('')}
           </select></div>`;
    }
  }
  let _showStandard = true;
  function _toggleStandard(){ _showStandard = !_showStandard; _renderGlassPanes(selectedPane()); }
  function _renderGlassPanes(pane){
    const body = document.getElementById('p2glassBody');
    if(!body) return;
    const units = GLASS_UNITS.filter(u => u.std === _showStandard);
    const otherCount = GLASS_UNITS.filter(u=>u.std !== _showStandard).length;
    body.innerHTML =
      `<button class="p2-btn ghost" style="margin-bottom:12px;" onclick="QSPhase2._toggleStandard()">
         ${_showStandard ? 'View Non-Standard Units ↑' : 'View Standard Units ↑'}
       </button>
       <div class="p2-note">Choose a ${_showStandard?'Standard':'Non-Standard'} Sealed Unit
         from <b style="color:var(--copper)">${units.length}</b> available:</div>
       <div class="p2-glass-list">` +
      units.map(u => `
        <div class="p2-glass-row ${pane&&pane.glazing===u.spec?'sel':''}" data-spec="${u.spec}"
             onclick="QSPhase2._pickGlass('${u.spec}','${u.name.replace(/'/g,"")}')">
          <span class="p2-glass-nm">${u.name}</span>
          <span class="p2-glass-icons">
            ${u.acoustic?'<span title="Acoustic">🔊</span>':''}
            ${u.solar?'<span title="Solar control">☀️</span>':''}
          </span>
        </div>`).join('') + `</div>`;
  }
  function _pickGlass(spec, name) {
    _pendingGlass = { spec, name };
    document.querySelectorAll('.p2-glass-card').forEach(c =>
      c.classList.toggle('sel', c.dataset.spec === spec));
  }
  function _pendTex()    { _pendingTex = document.getElementById('glassTex').value; }
  function _pendSpacer() { _pendingSpacer = document.getElementById('glassSpacer').value; }
  function _applyGlass(scope) {
    const apply = (p) => {
      if (_pendingGlass) p.glazing = _pendingGlass.spec;
      if (_pendingTex)   p.texture = _pendingTex;
      if (_pendingSpacer)p.spacer  = _pendingSpacer;
    };
    if (scope === 'all') window.model.panes.forEach(apply);
    else apply(selectedPane());   // 'pane' and 'selected' same here (single selection)
    _pendingGlass = _pendingTex = _pendingSpacer = null;
    commit(); closeModal();
  }

  /* ---------- expose ---------- */
  window.QSPhase2 = {
    openOpeners, openProfile, openFinish, openGlass, close: closeModal,
    _pickOpen, _applyOpen,
    _profTab, _profToggle, _profSelect,
    _finishTab, _pickFinish, _applyFinish,
    _glassTab, _pickGlass, _pendTex, _pendSpacer, _applyGlass, _toggleStandard, _renderGlassPanes,
    OPENING_TYPES, FINISH_COLOURS,
  };
})();