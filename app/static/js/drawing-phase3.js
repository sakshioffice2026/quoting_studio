/* ============================================================
   QUOTING STUDIO — DRAWING ENGINE PHASE 3
   Easy Draw (glazing bars) · Dimension Editor · Hardware · Extras

   Adds a GLAZING sub-toolbar (Select/Draw/Erase/Dimensions/Auto Grid/Clear),
   click-to-edit dimension boxes with Equalise, and hardware/extras catalogs.
   Attaches to window.QSDraw, global `model`, `dc`.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- hardware & extras catalogs ---------- */
  // Hardware categories with product cards (name + swatch colour for the card)
  const HARDWARE_CATS = {
    'Catch':            [
      {n:'None',c:null},{n:'Standard Cockspur',c:'#c9c9cc'},{n:'Espagnolette',c:'#b8b8bc'},
      {n:'Monkey Tail',c:'#2a2a2a'},{n:'Cranked',c:'#8a6d3b'}],
    'Sash Lift':        [
      {n:'None',c:null},{n:'Hook Lift',c:'#c9c9cc'},{n:'Flush Ring Lift',c:'#d4af37'},
      {n:'Bar Lift',c:'#2a2a2a'}],
    'Sash Ring':        [
      {n:'None',c:null},{n:'Standard Ring',c:'#c9c9cc'},{n:'Heritage Ring',c:'#8a6d3b'}],
    'Travel Restrictor':[
      {n:'None',c:null},{n:'Shark Fin - Antique Black',c:'#1c1c1c'},
      {n:'Shark Fin - Bronze',c:'#5c4733'},{n:'Shark Fin - Chrome',c:'#c9c9cc'},
      {n:'Shark Fin - Gold',c:'#d4af37'}],
    'Ventilation':      [
      {n:'None',c:null},{n:'Trickle Vent 4000',c:'#e8e4da'},
      {n:'Trickle Vent 5000',c:'#e8e4da'},{n:'Acoustic Vent',c:'#d8d4c8'}],
  };
  const HW_QTY = ['1 per sash','2 per sash','1 per window','2 per window','4 per window'];

  const EXTRAS = [
    { key:'diamondLead',   name:'Diamond lead',         hasQty:true,  price:45 },
    { key:'acousticVent',  name:'Acoustic trickle vent', hasQty:true,  price:32 },
    { key:'bayPosts',      name:'Bay posts',             hasQty:true,  price:78 },
    { key:'fixingBrackets',name:'Fixing brackets',       hasQty:true,  price:6  },
    { key:'archedHead',    name:'Arched / Raked head',   hasQty:false, price:120 },
    { key:'georgianBar',   name:'Georgian bar upgrade',  hasQty:false, price:55 },
  ];

  const GLASS_SIGHTLINE_OFFSET = 111; // pane inner - sightline (frame rebate), mm

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
     GLAZING SUB-TOOLBAR  (rendered into the Easy Draw tab)
     ============================================================ */
  function glazingToolbarHTML() {
    const tools = [
      ['select','Select & Edit','◱'],
      ['draw','Draw','✎'],
      ['erase','Erase','⌫'],
      ['dims','Dimensions','⊟'],
      ['autogrid','Auto Grid','▦'],
      ['clear','Clear','🗑'],
    ];
    const cur = window._glazeTool || 'draw';
    return `<div class="p3-gtoolbar">` +
      tools.map(([k,label,icon]) =>
        `<button class="p3-gtool ${k===cur?'on':''}" data-gt="${k}"
                 onclick="QSPhase3.glazeTool('${k}')">
           <span class="ic">${icon}</span>${label}
         </button>`).join('') +
      `</div>`;
  }

  function glazeTool(t) {
    window._glazeTool = t;
    if (t === 'clear')    { _clearAllBars(); window._glazeTool='draw'; }
    else if (t==='autogrid') { openAutoGrid(); window._glazeTool='draw'; }
    else if (t==='dims')  { openDimensionEditor(); window._glazeTool='select'; }
    else {
      // map to canvas tool
      window.dc.setTool(t==='draw' ? 'easydraw'
                       : t==='erase' ? 'eraseBar'
                       : 'select');
    }
    // refresh toolbar highlight
    document.querySelectorAll('.p3-gtool').forEach(b =>
      b.classList.toggle('on', b.dataset.gt === window._glazeTool));
    if (window.setTool && (t==='draw'||t==='select')) {
      // keep the rail in sync visually
    }
  }

  function _clearAllBars() {
    window.model.panes.forEach(p => p.glazingBars = []);
    commit();
  }

  /* ============================================================
     AUTO GRID  — create an N×M glazing bar pattern on a pane
     ============================================================ */
  function openAutoGrid() {
    const pane = selectedPane();
    modal('Auto Grid — glazing bars',
      `<div class="p3-note">Create a Georgian grid on the selected pane.</div>
       <div class="p3-row2">
         <div class="p3-field"><label>Columns (vertical bars)</label>
           <input type="number" id="agCols" value="2" min="1" max="8"></div>
         <div class="p3-field"><label>Rows (horizontal bars)</label>
           <input type="number" id="agRows" value="2" min="1" max="8"></div>
       </div>
       <div class="p3-field"><label>Bar thickness (mm)</label>
         <input type="number" id="agThick" value="18" min="6" max="40" step="2"></div>
       <div class="p3-toggle-row">
         <label class="p3-switch"><input type="checkbox" id="agAll"><span class="p3-slider"></span></label>
         <label for="agAll">Apply to all panes</label>
       </div>`,
      `<button class="p3-btn ghost" onclick="QSPhase3.close()">Cancel</button>
       <button class="p3-btn primary" onclick="QSPhase3._applyAutoGrid()">Create grid</button>`);
  }
  function _applyAutoGrid() {
    const cols = Math.max(1, +document.getElementById('agCols').value||2);
    const rows = Math.max(1, +document.getElementById('agRows').value||2);
    const thick= +document.getElementById('agThick').value||18;
    const all  = document.getElementById('agAll').checked;
    const targets = all ? window.model.panes : [selectedPane()];
    targets.forEach(pane => {
      pane.glazingBars = [];
      for (let c=1; c<cols; c++)
        pane.glazingBars.push({ type:'vertical',   pos:c/cols, thickness:thick });
      for (let r=1; r<rows; r++)
        pane.glazingBars.push({ type:'horizontal', pos:r/rows, thickness:thick });
    });
    commit(); closeModal();
  }

  /* ============================================================
     DIMENSION EDITOR  — click-to-edit + equalise
     ============================================================ */
  function openDimensionEditor() {
    const W = window.model.width, H = window.model.height;
    // gather unique column widths and row heights from pane grid
    const cols = uniqueEdges(window.model.panes.map(p => [p.x, p.x+p.w]), W);
    const rows = uniqueEdges(window.model.panes.map(p => [p.y, p.y+p.h]), H);

    const colInputs = cols.segments.map((seg,i) =>
      `<div class="p3-dim-line">
         <span class="p3-dim-idx">W${i+1}</span>
         <input type="number" class="p3-dim-in" data-axis="col" data-i="${i}"
                value="${Math.round(seg)}">
         <span class="p3-sightline">Glass sightline: <b>${Math.round(seg - GLASS_SIGHTLINE_OFFSET)}</b></span>
       </div>`).join('');
    const rowInputs = rows.segments.map((seg,i) =>
      `<div class="p3-dim-line">
         <span class="p3-dim-idx">H${i+1}</span>
         <input type="number" class="p3-dim-in" data-axis="row" data-i="${i}"
                value="${Math.round(seg)}">
         <span class="p3-sightline">Glass sightline: <b>${Math.round(seg)}</b></span>
       </div>`).join('');

    modal('Change Glazing Dimensions',
      `<div class="p3-note">Overall: ${W} × ${H} mm. Edit segment sizes below; the frame auto-redistributes.</div>
       ${cols.segments.length>1 ? `<div class="sec-head">Widths (mm)</div>${colInputs}` : ''}
       ${rows.segments.length>1 ? `<div class="sec-head" style="margin-top:14px;">Heights (mm)</div>${rowInputs}` : ''}
       <div class="p3-row2" style="margin-top:16px;">
         <button class="p3-btn ghost" onclick="QSPhase3._equalise('col')">Equalise Widths</button>
         <button class="p3-btn ghost" onclick="QSPhase3._equalise('row')">Equalise Heights</button>
       </div>
       <div class="p3-field" style="margin-top:14px;">
         <label>Overall width (mm)</label>
         <input type="number" id="dimW" value="${W}" step="10"></div>
       <div class="p3-field">
         <label>Overall height (mm)</label>
         <input type="number" id="dimH" value="${H}" step="10"></div>`,
      `<button class="p3-btn ghost" onclick="QSPhase3.close()">Close</button>
       <button class="p3-btn primary" onclick="QSPhase3._applyDims()">Apply</button>`);
  }

  function uniqueEdges(pairs, total) {
    const edges = new Set([0, 1]);
    pairs.forEach(([a,b]) => { edges.add(+a.toFixed(4)); edges.add(+b.toFixed(4)); });
    const sorted = [...edges].sort((a,b)=>a-b);
    const segments = [];
    for (let i=0;i<sorted.length-1;i++) segments.push((sorted[i+1]-sorted[i])*total);
    return { edges: sorted, segments };
  }

  function _equalise(axis) {
    const inputs = [...document.querySelectorAll(`.p3-dim-in[data-axis="${axis}"]`)];
    if (!inputs.length) return;
    const total = inputs.reduce((s,el)=>s+(+el.value||0),0);
    const eq = Math.round(total/inputs.length);
    inputs.forEach(el => el.value = eq);
  }

  function _applyDims() {
    const W = +document.getElementById('dimW').value || window.model.width;
    const H = +document.getElementById('dimH').value || window.model.height;
    window.model.width = W; window.model.height = H;

    // rebuild pane grid from edited segment sizes
    _rebuildFromSegments('col', W);
    _rebuildFromSegments('row', H);

    if (window.dc) { window.dc.fitView(); }
    // sync width/height inputs in the panel
    const fw=document.getElementById('fW'), fh=document.getElementById('fH');
    if (fw) fw.value=W; if (fh) fh.value=H;
    commit(); closeModal();
  }

  function _rebuildFromSegments(axis, total) {
    const inputs = [...document.querySelectorAll(`.p3-dim-in[data-axis="${axis}"]`)];
    if (inputs.length < 2) return;
    const sizes = inputs.map(el => +el.value||0);
    const sum = sizes.reduce((a,b)=>a+b,0) || 1;
    // normalised cumulative edges
    const edges = [0];
    let acc = 0;
    sizes.forEach(s => { acc += s/sum; edges.push(+acc.toFixed(4)); });
    // snap existing panes to nearest new edge band (best-effort redistribution)
    window.model.panes.forEach(p => {
      if (axis==='col') {
        const startBand = nearestBand(p.x, edges);
        const endBand   = nearestBand(p.x+p.w, edges);
        p.x = edges[startBand];
        p.w = Math.max(0.02, edges[Math.max(endBand,startBand+1)] - edges[startBand]);
      } else {
        const startBand = nearestBand(p.y, edges);
        const endBand   = nearestBand(p.y+p.h, edges);
        p.y = edges[startBand];
        p.h = Math.max(0.02, edges[Math.max(endBand,startBand+1)] - edges[startBand]);
      }
    });
  }
  function nearestBand(v, edges) {
    let best=0, bd=1e9;
    edges.forEach((e,i)=>{ const d=Math.abs(e-v); if(d<bd){bd=d;best=i;} });
    return best;
  }

  /* ============================================================
     HARDWARE  (right-panel content)
     ============================================================ */
  function hardwareHTML() {
    const hw = window.model.hardware || (window.model.hardware = {});
    // quick summary + open-modal button
    const chosen = Object.keys(HARDWARE_CATS).filter(c => hw[c] && hw[c]!=='None' && hw[c].sel && hw[c].sel!=='None');
    const summary = chosen.length
      ? chosen.map(c=>`<div class="p3-hw-sum"><b>${c}:</b> ${hw[c].sel} ${hw[c].qty?('· '+hw[c].qty):''}</div>`).join('')
      : '<div class="p3-note">No hardware selected yet.</div>';
    return `<div class="sec-head">Hardware</div>${summary}
      <button class="split-btn" style="width:100%;margin-top:8px;" onclick="QSPhase3.openHardware()">⊞ Manage Hardware…</button>`;
  }

  let _hwCurTab = 'Catch';
  function openHardware() {
    _hwCurTab = 'Catch';
    modal('Manage Hardware',
      `<div class="p2-tabs" id="hwTabs">
         ${Object.keys(HARDWARE_CATS).map((c,i)=>
           `<div class="p2-tab ${i===0?'on':''}" data-t="${c}" onclick="QSPhase3._hwTab('${c}')">${c.toUpperCase()}</div>`).join('')}
       </div>
       <div id="hwBody"></div>`,
      `<button class="p3-btn primary" onclick="QSPhase3.close()">Done</button>`);
    _hwRenderTab();
  }
  function _hwTab(c){ _hwCurTab=c;
    document.querySelectorAll('#hwTabs .p2-tab').forEach(el=>el.classList.toggle('on',el.dataset.t===c));
    _hwRenderTab();
  }
  function _hwRenderTab(){
    const hw = window.model.hardware || (window.model.hardware={});
    const cur = hw[_hwCurTab] || {sel:'None', qty:HW_QTY[0]};
    const cards = HARDWARE_CATS[_hwCurTab];
    const body = document.getElementById('hwBody');
    const on = cur.sel && cur.sel!=='None';
    body.innerHTML = `
      <div class="p3-toggle-row">
        <label class="p3-switch"><input type="checkbox" id="hwOn" ${on?'checked':''}
          onchange="QSPhase3._hwToggle()"><span class="p3-slider"></span></label>
        <label for="hwOn">${_hwCurTab}</label>
        <div style="margin-left:auto;display:flex;align-items:center;gap:8px;">
          <span style="font-size:12px;color:var(--steel);">Quantity:</span>
          <select id="hwQty" ${on?'':'disabled'} onchange="QSPhase3._hwQty()" style="width:130px;">
            ${HW_QTY.map(q=>`<option ${cur.qty===q?'selected':''}>${q}</option>`).join('')}
          </select>
        </div>
      </div>
      <div class="p3-toggle-row">
        <label class="p3-switch"><input type="checkbox" id="hwMatch" ${hw._matchColour?'checked':''}
          onchange="QSPhase3._hwMatch()"><span class="p3-slider"></span></label>
        <label for="hwMatch">Match Hardware Colour where possible</label>
      </div>
      <div class="p3-hw-grid">
        ${cards.filter(c=>c.n!=='None').map(c=>`
          <div class="p3-hw-card ${cur.sel===c.n?'sel':''}" onclick="QSPhase3._hwPick('${c.n.replace(/'/g,"")}')">
            <div class="p3-hw-sw" style="background:${c.c||'#eee'}"></div>
            <div class="p3-hw-nm">${c.n}</div>
          </div>`).join('')}
      </div>`;
  }
  function _hwToggle(){
    const hw=window.model.hardware;
    const on=document.getElementById('hwOn').checked;
    if(!on){ hw[_hwCurTab]={sel:'None'}; }
    else { hw[_hwCurTab]={sel:(HARDWARE_CATS[_hwCurTab][1]?.n||'Standard'), qty:HW_QTY[0]}; }
    _hwRenderTab(); _sync();
  }
  function _hwQty(){ const hw=window.model.hardware;
    if(!hw[_hwCurTab])hw[_hwCurTab]={sel:'None'}; hw[_hwCurTab].qty=document.getElementById('hwQty').value; _sync(); }
  function _hwMatch(){ window.model.hardware._matchColour=document.getElementById('hwMatch').checked; _sync(); }
  function _hwPick(name){ const hw=window.model.hardware;
    hw[_hwCurTab]={sel:name, qty:(hw[_hwCurTab]?.qty||HW_QTY[0])}; _hwRenderTab(); _sync(); }
  function _sync(){ if(window.scheduleSave)window.scheduleSave(); if(window.fetchPricing)window.fetchPricing(); if(window.renderTab)window.renderTab(); }

  // legacy setter kept for compatibility
  function setHardware(cat, val) {
    if (!window.model.hardware) window.model.hardware = {};
    window.model.hardware[cat] = {sel:val, qty:HW_QTY[0]};
    _sync();
  }

  /* ============================================================
     EXTRAS  (right-panel content)
     ============================================================ */
  function extrasHTML() {
    const ex = window.model.extras || (window.model.extras = {});
    const custom = (window.model.customExtras||[]).length;
    const presets = EXTRAS.filter(x=>ex[x.key]).length;
    const summary = (custom+presets)
      ? `<div class="p3-note">${presets} preset · ${custom} custom extra(s) selected.</div>`
      : '<div class="p3-note">No extras added.</div>';
    return `<div class="sec-head">Extras</div>${summary}
      <button class="split-btn" style="width:100%;margin-top:8px;" onclick="QSPhase3.openExtras()">⊞ Manage Item Extras…</button>`;
  }

  function openExtras() {
    modal('Manage Item Extras', _extrasBody(),
      `<button class="p3-btn ghost" onclick="QSPhase3.close()">Cancel</button>
       <button class="p3-btn primary" onclick="QSPhase3._applyExtras()">Apply</button>`);
  }
  function _extrasBody() {
    const ex = window.model.extras || (window.model.extras={});
    const customs = window.model.customExtras || (window.model.customExtras=[]);
    let html = `
      <div class="p3-toggle-row">
        <label class="p3-switch"><input type="checkbox" id="cxOn" ${customs.length?'checked':''}
          onchange="QSPhase3._toggleCustomSection()"><span class="p3-slider"></span></label>
        <label for="cxOn">Custom Extras</label>
      </div>
      <div id="cxList">${customs.map((c,i)=>_customRow(c,i)).join('')}</div>
      <button class="split-btn" style="margin-top:6px;" onclick="QSPhase3._addCustom()">+ Add another Custom Extra</button>
      <div class="p3-note" style="margin-top:8px;">Note: the price of a custom extra is added to the selling price after markups.</div>
      <div style="height:1px;background:var(--line);margin:16px 0;"></div>
      <div class="sec-head">Preset extras</div>`;
    html += EXTRAS.map(x=>{
      const on=!!ex[x.key];
      return `<div class="p3-toggle-row">
        <label class="p3-switch"><input type="checkbox" ${on?'checked':''}
          onchange="QSPhase3._togglePreset('${x.key}',this.checked)"><span class="p3-slider"></span></label>
        <label>${x.name} <span class="p3-price">£${x.price}</span></label>
        ${x.hasQty?`<input type="number" class="p3-qty" style="margin-left:auto;" min="1"
           value="${(ex[x.key]&&ex[x.key].qty)||1}" ${on?'':'disabled'}
           onchange="QSPhase3._presetQty('${x.key}',this.value)">`:''}
      </div>`;
    }).join('');
    return html;
  }
  function _customRow(c,i){
    return `<div class="p3-cx" data-i="${i}" style="border:1px solid var(--line);border-radius:6px;padding:12px;margin-bottom:10px;">
      <div class="p3-row2">
        <div class="p3-field"><label>Component</label><input value="${c.component||''}" onchange="QSPhase3._cxField(${i},'component',this.value)"></div>
        <div class="p3-field"><label>Quantity</label><input type="number" value="${c.qty||1}" onchange="QSPhase3._cxField(${i},'qty',this.value)"></div>
      </div>
      <div class="p3-row2">
        <div class="p3-field"><label>Price (£)</label><input type="number" value="${c.price||0}" onchange="QSPhase3._cxField(${i},'price',this.value)"></div>
        <div class="p3-field"><label>Supplier Name</label><input value="${c.supplier||''}" onchange="QSPhase3._cxField(${i},'supplier',this.value)"></div>
      </div>
      <div class="p3-field"><label>Supplier Quote Ref.</label><input value="${c.quoteRef||''}" onchange="QSPhase3._cxField(${i},'quoteRef',this.value)"></div>
      <div class="p3-field"><label>Note</label><input value="${c.note||''}" onchange="QSPhase3._cxField(${i},'note',this.value)"></div>
      <div class="p3-toggle-row"><label class="p3-switch"><input type="checkbox" ${c.includeRSV?'checked':''} onchange="QSPhase3._cxField(${i},'includeRSV',this.checked)"><span class="p3-slider"></span></label><label>Include in order to supplier</label></div>
      <div class="p3-toggle-row"><label class="p3-switch"><input type="checkbox" ${c.showOnImage?'checked':''} onchange="QSPhase3._cxField(${i},'showOnImage',this.checked)"><span class="p3-slider"></span></label><label>Show on item image</label></div>
      <button class="p3-btn ghost" style="border-color:#C0554A;color:#C0554A;" onclick="QSPhase3._delCustom(${i})">Delete extra</button>
    </div>`;
  }
  function _toggleCustomSection(){
    if(document.getElementById('cxOn').checked){ if(!window.model.customExtras.length)_addCustom(); }
    else { window.model.customExtras=[]; _refreshExtras(); }
  }
  function _addCustom(){ window.model.customExtras.push({component:'',qty:1,price:0}); _refreshExtras(); }
  function _delCustom(i){ window.model.customExtras.splice(i,1); _refreshExtras(); }
  function _cxField(i,f,v){ const c=window.model.customExtras[i]; if(!c)return;
    c[f]=(f==='qty'||f==='price')?(+v||0):(f==='includeRSV'||f==='showOnImage')?v:v; }
  function _togglePreset(key,on){ const ex=window.model.extras; const meta=EXTRAS.find(e=>e.key===key);
    if(on)ex[key]={qty:1,price:meta.price,name:meta.name}; else delete ex[key]; _refreshExtras(); }
  function _presetQty(key,q){ if(window.model.extras[key])window.model.extras[key].qty=Math.max(1,+q||1); }
  function _refreshExtras(){ const b=document.querySelector('#p3modal .p2-modal-body'); if(b)b.innerHTML=_extrasBody(); }
  function _applyExtras(){ closeModal();
    if(window.renderTab)window.renderTab(); if(window.scheduleSave)window.scheduleSave(); if(window.fetchPricing)window.fetchPricing(); }

  // legacy
  function toggleExtra(key,on){ _togglePreset(key,on); }
  function setExtraQty(key,qty){ _presetQty(key,qty); }

  /* ---------- modal shell (shared with phase2 styling) ---------- */
  function modal(title, body, foot) {
    closeModal();
    const back = document.createElement('div');
    back.className='p2-modal-back'; back.id='p3modal';
    back.innerHTML = `<div class="p2-modal">
      <div class="p2-modal-head"><h3>${title}</h3>
        <button class="p2-x" onclick="QSPhase3.close()">✕</button></div>
      <div class="p2-modal-body">${body}</div>
      <div class="p2-modal-foot">${foot}</div></div>`;
    back.addEventListener('mousedown', e=>{ if(e.target===back) closeModal(); });
    document.body.appendChild(back);
    requestAnimationFrame(()=>back.classList.add('show'));
  }
  function closeModal(){ const m=document.getElementById('p3modal'); if(m)m.remove(); }

  window.QSPhase3 = {
    glazingToolbarHTML, glazeTool,
    openAutoGrid, _applyAutoGrid,
    openDimensionEditor, _equalise, _applyDims,
    // hardware
    hardwareHTML, openHardware, _hwTab, _hwToggle, _hwQty, _hwMatch, _hwPick, setHardware,
    // extras
    extrasHTML, openExtras, _toggleCustomSection, _addCustom, _delCustom, _cxField,
    _togglePreset, _presetQty, _applyExtras, toggleExtra, setExtraQty,
    close: closeModal,
    EXTRAS,
  };
})();
