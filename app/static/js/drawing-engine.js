/* ============================================================
   QUOTING STUDIO — PARAMETRIC SVG DRAWING ENGINE
   Vanilla JS. No dependencies. Replaces the Three.js editor.

   Object hierarchy:
     Window ├ Frame ├ Sashes ├ Panes ├ GlazingBars ├ Hardware └ Extras

   Phase 1: Canvas (grid/zoom/pan/snap) + Templates + SVG render
   ============================================================ */

const SVGNS = 'http://www.w3.org/2000/svg';

/* ── Mullion/Transom span helpers ───────────────────────────────────────── */
// For each unique internal edge (rx or ty), collect the perpendicular spans
// of the panes that actually own that edge. Returns Map<edge, [[a,b]...]>.
function _collectEdgeSpans(panes, axis, W, H) {
  const map = new Map();
  for (const p of panes) {
    const edge = axis === 'v'
      ? +(p.x + p.w).toFixed(4)
      : +(p.y + p.h).toFixed(4);
    if (edge <= 0.001 || edge >= 0.999) continue;
    if (!map.has(edge)) map.set(edge, []);
    map.get(edge).push(
      axis === 'v'
        ? [p.y * H, (p.y + p.h) * H]
        : [p.x * W, (p.x + p.w) * W]
    );
  }
  return map;
}
// Merge overlapping/adjacent [a,b] ranges (input in any order).
function _mergeRanges(ranges) {
  if (!ranges.length) return [];
  const s = ranges.slice().sort((a, b) => a[0] - b[0]);
  const out = [[...s[0]]];
  for (let i = 1; i < s.length; i++) {
    const last = out[out.length - 1];
    if (s[i][0] <= last[1] + 0.5) { last[1] = Math.max(last[1], s[i][1]); }
    else out.push([...s[i]]);
  }
  return out;
}

/* ---------- MODEL ---------- */
class WindowModel {
  constructor(opts = {}) {
    this.id       = opts.id || 'win_' + Date.now().toString(36);
    this.width    = opts.width  || 1200;   // mm
    this.height   = opts.height || 1500;   // mm
    this.shape    = opts.shape || 'rectangle';   // rectangle|arched|gothic|circular
    this.archRise = opts.archRise != null ? opts.archRise : 400; // mm — head rise for arched/gothic
    this.unitType = opts.unitType || 'window';   // window|door
    this.door     = opts.door || { dtype:'single', leafCount:1, slL:0, slR:0, flH:0 };
    this.frame = {
      thickness: opts.frameThickness || 58,
      material : opts.material || 'Aluminium',
      color    : opts.color || '#2B2F33',
      colorName: opts.colorName || 'Anthracite',
      outerProfile: opts.outerProfile || 'Standard',
      innerProfile: opts.innerProfile || 'Standard',
      slimMullionClip: false,
      staffBead: true,
      flushSash: false,
      sashHorns: false,
      cill: opts.cill != null ? opts.cill : false,   // projecting cill below unit
      sashColor: opts.sashColor || '',               // '' = same as frame colour
      handleColor: opts.handleColor || 'chrome',     // chrome|black|gold|white
      handleType: opts.handleType || 'lever',         // lever|monkeytail|tbar|cockspur|knob
      ral: opts.ral || '',
    };
    this.hardware = opts.hardware || {};
    this.extras   = opts.extras   || {};
    this.customExtras = opts.customExtras || [];

    // panes: normalized 0..1 grid coordinates
    this.panes = opts.panes || [
      { id: 'p1', x: 0, y: 0, w: 1, h: 1,
        opening: 'Fixed', glazing: 'Double, Low-E',
        texture: 'Clear', spacer: 'Warm Edge Black',
        glazingBars: [] }
    ];
  }

  nextPaneId() { return 'p' + Math.random().toString(36).slice(2, 7); }

  splitPane(paneId, axis) {
    const i = this.panes.findIndex(p => p.id === paneId);
    if (i < 0) return null;
    const p = this.panes[i];
    const a = { ...p, id: this.nextPaneId(), glazingBars: [] };
    const b = { ...p, id: this.nextPaneId(), glazingBars: [] };
    if (axis === 'v') { a.w = p.w/2; b.w = p.w/2; b.x = p.x + p.w/2; }
    else              { a.h = p.h/2; b.h = p.h/2; b.y = p.y + p.h/2; }
    this.panes.splice(i, 1, a, b);
    return a.id;
  }

  // Split a pane at an exact distance (mm) measured from the pane's
  // left edge (vertical/mullion) or bottom edge (horizontal/transom).
  // Returns the id of the near-side (A) pane, or null.
  splitPaneAt(paneId, axis, posMm, opts = {}) {
    const MIN = opts.minPane || 100;   // mm
    const SNAP = opts.snap || 5;        // mm
    const i = this.panes.findIndex(p => p.id === paneId);
    if (i < 0) return null;
    const p = this.panes[i];

    // pane size in mm
    const paneW = p.w * this.width;
    const paneH = p.h * this.height;
    const span  = axis === 'v' ? paneW : paneH;

    // snap + clamp
    let pos = Math.round(posMm / SNAP) * SNAP;
    pos = Math.max(MIN, Math.min(span - MIN, pos));
    const frac = pos / span;   // 0..1 within the pane

    const a = { ...p, id: this.nextPaneId(), glazingBars: [] };
    const b = { ...p, id: this.nextPaneId(), glazingBars: [] };
    if (axis === 'v') {
      // "from left": A is the left portion of width `pos`
      a.w = p.w * frac;
      b.w = p.w * (1 - frac);
      b.x = p.x + a.w;
    } else {
      // "from bottom": in normalized coords y grows downward, so the
      // bottom edge is (p.y + p.h). A = bottom portion of height `pos`.
      const topH = p.h * (1 - frac);   // upper portion
      const botH = p.h * frac;         // lower portion (from bottom)
      a.y = p.y;         a.h = topH;   // top pane
      b.y = p.y + topH;  b.h = botH;   // bottom pane
    }
    this.panes.splice(i, 1, a, b);
    return a.id;
  }

  mergePane(paneId) {
    if (this.panes.length <= 1) return;
    const i = this.panes.findIndex(p => p.id === paneId);
    if (i < 0) return;
    const gone = this.panes[i];
    const EPS = 0.001;

    // Find a neighbor that shares a full edge with the deleted pane, so we
    // can expand it to cover the freed area instead of leaving a gap.
    let neighbor = null;
    for (const p of this.panes) {
      if (p.id === gone.id) continue;
      const sameRow = Math.abs(p.y - gone.y) < EPS && Math.abs(p.h - gone.h) < EPS;
      const sameCol = Math.abs(p.x - gone.x) < EPS && Math.abs(p.w - gone.w) < EPS;
      if (sameRow && Math.abs((p.x + p.w) - gone.x) < EPS) { neighbor = p; neighbor._grow = 'right'; break; }
      if (sameRow && Math.abs((gone.x + gone.w) - p.x) < EPS) { neighbor = p; neighbor._grow = 'left'; break; }
      if (sameCol && Math.abs((p.y + p.h) - gone.y) < EPS) { neighbor = p; neighbor._grow = 'up'; break; }
      if (sameCol && Math.abs((gone.y + gone.h) - p.y) < EPS) { neighbor = p; neighbor._grow = 'down'; break; }
    }

    if (neighbor) {
      if (neighbor._grow === 'right') { neighbor.w += gone.w; }
      else if (neighbor._grow === 'left') { neighbor.x = gone.x; neighbor.w += gone.w; }
      else if (neighbor._grow === 'up') { neighbor.h += gone.h; }
      else if (neighbor._grow === 'down') { neighbor.y = gone.y; neighbor.h += gone.h; }
      delete neighbor._grow;
      this.panes.splice(i, 1);
    } else if (this.panes.length === 2) {
      // Only one other pane left and it isn't a clean edge-neighbor (rare,
      // irregular grid) — expand it to cover the full frame rather than
      // leaving a hole.
      const survivor = this.panes.find(p => p.id !== gone.id);
      survivor.x = 0; survivor.y = 0; survivor.w = 1; survivor.h = 1;
      this.panes.splice(i, 1);
    } else {
      // No clean neighbor found among 3+ panes — deleting would leave a
      // gap, so refuse rather than corrupt the layout.
      return false;
    }
    return true;
  }

  // Split a pane into n equal parts along the given axis.
  equalisePane(paneId, axis, n) {
    n = Math.max(2, Math.min(20, +n || 2));
    const i = this.panes.findIndex(p => p.id === paneId);
    if (i < 0) return [];
    const p = this.panes[i];
    const newPanes = [];
    for (let k = 0; k < n; k++) {
      const np = { ...p, id: this.nextPaneId(), glazingBars: [] };
      if (axis === 'v') { np.w = p.w / n; np.x = p.x + k * (p.w / n); }
      else              { np.h = p.h / n; np.y = p.y + k * (p.h / n); }
      newPanes.push(np);
    }
    this.panes.splice(i, 1, ...newPanes);
    return newPanes.map(np => np.id);
  }

  toJSON() {
    return {
      id: this.id, width: this.width, height: this.height,
      shape: this.shape, archRise: this.archRise,
      unitType: this.unitType, door: this.door,
      frame: this.frame, panes: this.panes,
      hardware: this.hardware, extras: this.extras, customExtras: this.customExtras,
      profileRoles: this.profileRoles || {},
    };
  }

  static fromJSON(json) {
    const m = new WindowModel();
    // Merge top-level scalars safely; handle frame as a nested merge
    const { frame: savedFrame, panes, hardware, extras, customExtras, door, ...rest } = json || {};
    Object.assign(m, rest);
    // Deep-merge frame so defaults (thickness, material, etc.) survive
    if (savedFrame) Object.assign(m.frame, savedFrame);
    if (panes)       m.panes = panes;
    if (hardware)    m.hardware = hardware;
    if (extras)      m.extras = extras;
    if (customExtras) m.customExtras = customExtras;
    if (door)        m.door = { ...m.door, ...door };
    if (!m.frame) m.frame = {};
    if (!m.panes || !m.panes.length)
      m.panes = [{ id:'p1', x:0,y:0,w:1,h:1, opening:'Fixed',
                   glazing:'Double, Low-E', glazingBars:[] }];
    m.panes.forEach(p => {
      if (!p.glazingBars) p.glazingBars = [];
      if (!p.infill) p.infill = 'glass';
    });
    if (!m.hardware) m.hardware = {};
    if (!m.extras)   m.extras = {};
    if (!m.customExtras) m.customExtras = [];
    if (!m.shape)    m.shape = 'rectangle';
    if (m.archRise == null) m.archRise = 400;
    if (!m.unitType) m.unitType = 'window';
    if (!m.door)     m.door = { dtype:'single', leafCount:1, slL:0, slR:0, flH:0 };
    return m;
  }
}

/* ---------- TEMPLATES ----------
   Each template carries:
     name, unit ('window'|'door'), category, panels,
     panes[] (normalized x/y/w/h),
     optional shape, door{} config, and per-pane opening/bars overrides.
   The `unit` field lets the chooser filter window vs door templates.
------------------------------------------------------------------- */
const TEMPLATES = {
  /* ===================== WINDOWS ===================== */
  // — Basic —
  single: { name:'Single', unit:'window', category:'Basic', panels:1,
    panes:[{x:0,y:0,w:1,h:1}] },
  double: { name:'Double', unit:'window', category:'Basic', panels:2,
    panes:[{x:0,y:0,w:.5,h:1},{x:.5,y:0,w:.5,h:1}] },
  triple: { name:'Triple', unit:'window', category:'Basic', panels:3,
    panes:[{x:0,y:0,w:.34,h:1},{x:.34,y:0,w:.33,h:1},{x:.67,y:0,w:.33,h:1}] },
  quad: { name:'Quad (4 lights)', unit:'window', category:'Basic', panels:4,
    panes:[{x:0,y:0,w:.25,h:1},{x:.25,y:0,w:.25,h:1},{x:.5,y:0,w:.25,h:1},{x:.75,y:0,w:.25,h:1}] },

  // — Casement (opening lights around a fixed centre) —
  casement2: { name:'Casement 2-light', unit:'window', category:'Casement', panels:2,
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  casement3: { name:'Casement 3-light', unit:'window', category:'Casement', panels:3,
    panes:[{x:0,y:0,w:.28,h:1,opening:'Left Open'},{x:.28,y:0,w:.44,h:1,opening:'Fixed'},
           {x:.72,y:0,w:.28,h:1,opening:'Right Open'}] },
  casementTopVent: { name:'Casement + top vents', unit:'window', category:'Casement', panels:4,
    panes:[{x:0,y:0,w:.5,h:.28,opening:'Top Hung'},{x:.5,y:0,w:.5,h:.28,opening:'Top Hung'},
           {x:0,y:.28,w:.5,h:.72,opening:'Left Open'},{x:.5,y:.28,w:.5,h:.72,opening:'Right Open'}] },

  // — Sash (traditional vertical sliders) —
  sash: { name:'Sash (top/bottom)', unit:'window', category:'Sash', panels:2,
    panes:[{x:0,y:0,w:1,h:.5,opening:'Sliding'},{x:0,y:.5,w:1,h:.5,opening:'Sliding'}] },
  sash2over2: { name:'Sash 2 over 2', unit:'window', category:'Sash', panels:2,
    shape:'rectangle',
    panes:[{x:0,y:0,w:1,h:.5,opening:'Sliding',bars:{v:1}},
           {x:0,y:.5,w:1,h:.5,opening:'Sliding',bars:{v:1}}] },
  sash6over6: { name:'Sash 6 over 6 (Georgian)', unit:'window', category:'Sash', panels:2,
    panes:[{x:0,y:0,w:1,h:.5,opening:'Sliding',bars:{v:2,h:1}},
           {x:0,y:.5,w:1,h:.5,opening:'Sliding',bars:{v:2,h:1}}] },
  sashMarginal: { name:'Sash marginal bars', unit:'window', category:'Sash', panels:2,
    panes:[{x:0,y:0,w:1,h:.5,opening:'Sliding',bars:{v:1}},
           {x:0,y:.5,w:1,h:.5,opening:'Sliding',bars:{v:1}}] },

  // — Georgian / bar grids —
  twoOverTwo: { name:'2 over 2', unit:'window', category:'Georgian', panels:4,
    panes:[{x:0,y:0,w:.5,h:.5},{x:.5,y:0,w:.5,h:.5},
           {x:0,y:.5,w:.5,h:.5},{x:.5,y:.5,w:.5,h:.5}] },
  georgian3x2: { name:'Georgian 3×2', unit:'window', category:'Georgian', panels:1,
    panes:[{x:0,y:0,w:1,h:1,bars:{v:2,h:1}}] },
  georgian4x3: { name:'Georgian 4×3', unit:'window', category:'Georgian', panels:1,
    panes:[{x:0,y:0,w:1,h:1,bars:{v:3,h:2}}] },

  // — Cottage / stacked —
  cottage: { name:'Cottage (small top row)', unit:'window', category:'Cottage', panels:6,
    panes:[{x:0,y:0,w:.34,h:.32},{x:.34,y:0,w:.33,h:.32},{x:.67,y:0,w:.33,h:.32},
           {x:0,y:.32,w:.34,h:.68},{x:.34,y:.32,w:.33,h:.68},{x:.67,y:.32,w:.33,h:.68}] },
  threeOverOne: { name:'3 over 1', unit:'window', category:'Cottage', panels:4,
    panes:[{x:0,y:0,w:.34,h:.4},{x:.34,y:0,w:.33,h:.4},{x:.67,y:0,w:.33,h:.4},
           {x:0,y:.4,w:1,h:.6}] },

  // — Bay / bow (rendered flat; angle noted in label) —
  bay3: { name:'Bay 3-facet', unit:'window', category:'Bay', panels:3,
    panes:[{x:0,y:0,w:.26,h:1,opening:'Left Open'},{x:.26,y:0,w:.48,h:1,opening:'Fixed'},
           {x:.74,y:0,w:.26,h:1,opening:'Right Open'}] },
  bay5: { name:'Bow 5-facet', unit:'window', category:'Bay', panels:5,
    panes:[{x:0,y:0,w:.2,h:1},{x:.2,y:0,w:.2,h:1},{x:.4,y:0,w:.2,h:1},
           {x:.6,y:0,w:.2,h:1},{x:.8,y:0,w:.2,h:1}] },

  // — Shaped —
  archedSingle: { name:'Arched single', unit:'window', category:'Shaped', panels:1,
    shape:'arched', panes:[{x:0,y:0,w:1,h:1}] },
  archedDouble: { name:'Arched double', unit:'window', category:'Shaped', panels:2,
    shape:'arched', panes:[{x:0,y:0,w:.5,h:1},{x:.5,y:0,w:.5,h:1}] },
  gothic: { name:'Gothic top', unit:'window', category:'Shaped', panels:1,
    shape:'gothic', panes:[{x:0,y:0,w:1,h:1}] },
  circular: { name:'Circular', unit:'window', category:'Shaped', panels:1,
    shape:'circular', panes:[{x:0,y:0,w:1,h:1}] },

  /* ===================== DOORS ===================== */
  // — Single leaf —
  doorSingle: { name:'Single door', unit:'door', category:'Single', panels:1,
    door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open'}] },
  doorHalfGlazed: { name:'Single half-glazed', unit:'door', category:'Single', panels:2,
    door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:.5,opening:'Fixed',glazing:'Double, Low-E'},
           {x:0,y:.5,w:1,h:.5,opening:'Right Open'}] },
  doorFullGlazed: { name:'Single full-glazed', unit:'door', category:'Single', panels:1,
    door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open',glazing:'Double, Low-E'}] },
  doorGeorgian: { name:'Single Georgian', unit:'door', category:'Single', panels:1,
    door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open',bars:{v:1,h:2}}] },

  // — Double leaf —
  doorDouble: { name:'Double door', unit:'door', category:'Double', panels:2,
    door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  doorFrench: { name:'French doors', unit:'door', category:'Double', panels:2,
    door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open',glazing:'Double, Low-E'},
           {x:.5,y:0,w:.5,h:1,opening:'Right Open',glazing:'Double, Low-E'}] },
  doorFrenchGeorgian: { name:'French Georgian', unit:'door', category:'Double', panels:2,
    door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open',bars:{v:1,h:3}},
           {x:.5,y:0,w:.5,h:1,opening:'Right Open',bars:{v:1,h:3}}] },

  // — With sidelights / fanlight —
  doorSideL: { name:'Door + sidelight L', unit:'door', category:'Sidelight', panels:2,
    door:{dtype:'sl',leafCount:1,slL:300,slR:0,flH:0},
    panes:[{x:0,y:0,w:.25,h:1,opening:'Fixed'},{x:.25,y:0,w:.75,h:1,opening:'Right Open'}] },
  doorSideR: { name:'Door + sidelight R', unit:'door', category:'Sidelight', panels:2,
    door:{dtype:'sr',leafCount:1,slL:0,slR:300,flH:0},
    panes:[{x:0,y:0,w:.75,h:1,opening:'Left Open'},{x:.75,y:0,w:.25,h:1,opening:'Fixed'}] },
  doorSideBoth: { name:'Door + 2 sidelights', unit:'door', category:'Sidelight', panels:3,
    door:{dtype:'full',leafCount:1,slL:250,slR:250,flH:0},
    panes:[{x:0,y:0,w:.22,h:1,opening:'Fixed'},{x:.22,y:0,w:.56,h:1,opening:'Right Open'},
           {x:.78,y:0,w:.22,h:1,opening:'Fixed'}] },
  doorFanlight: { name:'Door + fanlight', unit:'door', category:'Sidelight', panels:2,
    door:{dtype:'fan',leafCount:1,slL:0,slR:0,flH:400},
    panes:[{x:0,y:0,w:1,h:.25,opening:'Fixed'},{x:0,y:.25,w:1,h:.75,opening:'Right Open'}] },
  doorFullSet: { name:'Full set (2 side + fan)', unit:'door', category:'Sidelight', panels:5,
    door:{dtype:'full',leafCount:2,slL:250,slR:250,flH:350},
    panes:[{x:0,y:0,w:1,h:.22,opening:'Fixed'},
           {x:0,y:.22,w:.22,h:.78,opening:'Fixed'},
           {x:.22,y:.22,w:.28,h:.78,opening:'Left Open'},
           {x:.5,y:.22,w:.28,h:.78,opening:'Right Open'},
           {x:.78,y:.22,w:.22,h:.78,opening:'Fixed'}] },

  // — Bifold (2–6 leaf) —
  bifold2: { name:'Bifold 2-leaf', unit:'door', category:'Bifold', panels:2,
    door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  bifold3: { name:'Bifold 3-leaf', unit:'door', category:'Bifold', panels:3,
    door:{dtype:'double',leafCount:3,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.334,h:1,opening:'Left Open'},{x:.334,y:0,w:.333,h:1,opening:'Left Open'},
           {x:.667,y:0,w:.333,h:1,opening:'Right Open'}] },
  bifold4: { name:'Bifold 4-leaf', unit:'door', category:'Bifold', panels:4,
    door:{dtype:'double',leafCount:4,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.25,h:1,opening:'Left Open'},{x:.25,y:0,w:.25,h:1,opening:'Left Open'},
           {x:.5,y:0,w:.25,h:1,opening:'Right Open'},{x:.75,y:0,w:.25,h:1,opening:'Right Open'}] },
  bifold5: { name:'Bifold 5-leaf', unit:'door', category:'Bifold', panels:5,
    door:{dtype:'double',leafCount:5,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.2,h:1,opening:'Left Open'},{x:.2,y:0,w:.2,h:1,opening:'Left Open'},
           {x:.4,y:0,w:.2,h:1,opening:'Left Open'},{x:.6,y:0,w:.2,h:1,opening:'Right Open'},
           {x:.8,y:0,w:.2,h:1,opening:'Right Open'}] },
  bifold6: { name:'Bifold 6-leaf', unit:'door', category:'Bifold', panels:6,
    door:{dtype:'double',leafCount:6,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.1667,h:1,opening:'Left Open'},{x:.1667,y:0,w:.1667,h:1,opening:'Left Open'},
           {x:.3334,y:0,w:.1666,h:1,opening:'Left Open'},{x:.5,y:0,w:.1667,h:1,opening:'Right Open'},
           {x:.6667,y:0,w:.1667,h:1,opening:'Right Open'},{x:.8334,y:0,w:.1666,h:1,opening:'Right Open'}] },

  // — Sliding patio —
  patioSlide2: { name:'Sliding patio 2-pane', unit:'door', category:'Sliding', panels:2,
    door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Sliding'},{x:.5,y:0,w:.5,h:1,opening:'Fixed'}] },
  patioSlide3: { name:'Sliding patio 3-pane', unit:'door', category:'Sliding', panels:3,
    door:{dtype:'double',leafCount:3,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.333,h:1,opening:'Fixed'},{x:.333,y:0,w:.334,h:1,opening:'Sliding'},
           {x:.667,y:0,w:.333,h:1,opening:'Fixed'}] },

  // — Shaped doors (arched / gothic top) —
  doorArchedSingle:     { name:'Arched single door',       unit:'door', category:'Shaped', panels:1,
    shape:'arched', door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open'}] },
  doorArchedHalfGlazed: { name:'Arched half-glazed',       unit:'door', category:'Shaped', panels:2,
    shape:'arched', door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:.45,opening:'Fixed'},{x:0,y:.45,w:1,h:.55,opening:'Right Open'}] },
  doorArchedDouble:     { name:'Arched double door',        unit:'door', category:'Shaped', panels:2,
    shape:'arched', door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  doorArchedFrench:     { name:'Arched French doors',       unit:'door', category:'Shaped', panels:2,
    shape:'arched', door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  doorArchedWithSides:  { name:'Arched + sidelights',       unit:'door', category:'Shaped', panels:3,
    shape:'arched', door:{dtype:'full',leafCount:1,slL:250,slR:250,flH:0},
    panes:[{x:0,y:0,w:.22,h:1,opening:'Fixed'},{x:.22,y:0,w:.56,h:1,opening:'Right Open'},
           {x:.78,y:0,w:.22,h:1,opening:'Fixed'}] },
  doorGothicSingle:     { name:'Gothic single door',        unit:'door', category:'Shaped', panels:1,
    shape:'gothic', door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open'}] },
  doorGothicDouble:     { name:'Gothic double door',        unit:'door', category:'Shaped', panels:2,
    shape:'gothic', door:{dtype:'double',leafCount:2,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:.5,h:1,opening:'Left Open'},{x:.5,y:0,w:.5,h:1,opening:'Right Open'}] },
  doorArchedGeorgian:   { name:'Arched Georgian door',      unit:'door', category:'Shaped', panels:1,
    shape:'arched', door:{dtype:'single',leafCount:1,slL:0,slR:0,flH:0},
    panes:[{x:0,y:0,w:1,h:1,opening:'Right Open',bars:{v:1,h:3}}] },
};

/* Build glazing bars for a pane from a {v,h} bar-count spec. */
function _barsFromSpec(spec) {
  if (!spec) return [];
  const bars = [];
  const nv = spec.v || 0, nh = spec.h || 0;
  for (let i = 1; i <= nv; i++) bars.push({ type:'vertical',   pos: i/(nv+1), thickness:18 });
  for (let j = 1; j <= nh; j++) bars.push({ type:'horizontal', pos: j/(nh+1), thickness:18 });
  return bars;
}

function templateToPanes(tplKey) {
  const t = TEMPLATES[tplKey] || TEMPLATES.single;
  const isDoor = t.unit === 'door';
  return t.panes.map((c, i) => {
    // Infill rule:
    //  - explicit c.infill wins
    //  - windows are always glass
    //  - door panes that are glazed (have `glazing` set, or `bars`, or are
    //    sidelights/fanlights/sliding) are glass; plain door leaves are solid panel
    let infill = c.infill;
    if (!infill) {
      if (!isDoor) infill = 'glass';
      else if (c.glazing || c.bars) infill = 'glass';
      else if (c.opening === 'Fixed' || c.opening === 'Sliding') infill = 'glass'; // sidelights/fanlights/patio
      else infill = 'panel';   // solid door leaf
    }
    return {
      id: 'p' + (i+1), x: c.x, y: c.y, w: c.w, h: c.h,
      opening: c.opening || 'Fixed',
      glazing: c.glazing || 'Double, Low-E',
      infill,
      glazingBars: _barsFromSpec(c.bars),
    };
  });
}

/* Full template application: returns { panes, shape, unitType, door } so the
   editor can seed the whole model (not just panes) from a chosen template. */
function templateToModel(tplKey) {
  const t = TEMPLATES[tplKey] || TEMPLATES.single;
  return {
    panes:    templateToPanes(tplKey),
    shape:    t.shape || 'rectangle',
    unitType: t.unit || 'window',
    door:     t.door ? { ...t.door } : { dtype:'single', leafCount:1, slL:0, slR:0, flH:0 },
  };
}

/* Templates grouped by unit + category, for the chooser UI. */
function templatesByCategory(unit) {
  const out = {};
  for (const [key, t] of Object.entries(TEMPLATES)) {
    if (unit && t.unit !== unit) continue;
    const cat = t.category || 'Other';
    (out[cat] = out[cat] || []).push({ key, ...t });
  }
  return out;
}

/* ---------- CANVAS / RENDERER ---------- */
class DrawingCanvas {
  constructor(svgEl, model, opts = {}) {
    this.svg    = svgEl;
    this.model  = model;
    this.scale  = 0.28;            // px per mm (zoom)
    this.panX   = 0;
    this.panY   = 0;
    this.grid   = 25;              // grid size in mm
    this.snap   = true;
    this.selectedPaneId = model.panes[0]?.id || null;
    this.tool   = 'select';
    this.onSelect        = opts.onSelect || (()=>{});
    this.onChange        = opts.onChange || (()=>{});
    this.onHistoryChange = opts.onHistoryChange || null;
    this.onMemberPlace   = opts.onMemberPlace || null;
    this.onProfileDeselect = opts.onProfileDeselect || null;  // fired when a canvas highlight is clicked to deselect
    this.easyDrawState = null;
    this.showProfileHighlights = false;   // ON while the Profiles tab is active
    this._pulseRole = null;               // role glowing from sidebar hover
    this._hoverRole = null;               // role currently hovered directly on the canvas

    // undo/redo history
    this._history = [];
    this._historyIdx = -1;
    this._maxHistory = 50;

    this._bindEvents();
    this.centerView();
    this.render();
    this._pushHistory();   // initial state
  }

  // ---- undo/redo ----
  _pushHistory() {
    // truncate any redo branch
    this._history = this._history.slice(0, this._historyIdx + 1);
    this._history.push(JSON.stringify(this.model.toJSON()));
    if (this._history.length > this._maxHistory) this._history.shift();
    this._historyIdx = this._history.length - 1;
  }
  canUndo() { return this._historyIdx > 0; }
  canRedo() { return this._historyIdx < this._history.length - 1; }
  undo() {
    if (!this.canUndo()) return false;
    this._historyIdx--;
    this._restoreHistory();
    return true;
  }
  redo() {
    if (!this.canRedo()) return false;
    this._historyIdx++;
    this._restoreHistory();
    return true;
  }
  _restoreHistory() {
    const json = JSON.parse(this._history[this._historyIdx]);
    const M = window.QSDraw.WindowModel;
    const m = M.fromJSON(json);
    this.model = m;
    window.model = m;
    if (!this.model.panes.find(p => p.id === this.selectedPaneId))
      this.selectedPaneId = this.model.panes[0]?.id;
    this.render();
    if (this.onHistoryChange) this.onHistoryChange();
    if (this.onChange) this.onChange(true);  // true = skip history push
  }

  /* ----- coordinate transforms ----- */
  mmToPx(mm) { return mm * this.scale; }
  worldToScreen(x, y) {
    return { x: x*this.scale + this.panX, y: y*this.scale + this.panY };
  }
  screenToWorld(sx, sy) {
    return { x: (sx - this.panX)/this.scale, y: (sy - this.panY)/this.scale };
  }
  snapVal(v) { return this.snap ? Math.round(v/this.grid)*this.grid : v; }

  centerView() {
    const rect = this.svg.getBoundingClientRect();
    const w = this.mmToPx(this.model.width);
    const h = this.mmToPx(this.model.height);
    this.panX = (rect.width  - w)/2;
    this.panY = (rect.height - h)/2;
  }

  fitView() {
    const rect = this.svg.getBoundingClientRect();
    const margin = 80;
    const sx = (rect.width  - margin*2) / this.model.width;
    const sy = (rect.height - margin*2) / this.model.height;
    this.scale = Math.min(sx, sy);
    this.centerView();
    this.render();
  }

  setTool(t) { this.tool = t; this.svg.style.cursor =
    t==='select' ? 'default' : t==='pan' ? 'grab' :
    t==='eraseBar' ? 'pointer' : 'crosshair';
    if (t !== 'eraseBar' && this._hoverBar) { this._hoverBar = null; this.render(); } }

  /* ----- events ----- */
  _bindEvents() {
    let isPanning = false, startX=0, startY=0, startPanX=0, startPanY=0;

    this.svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = this.svg.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const before = this.screenToWorld(mx, my);
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      this.scale = Math.max(0.05, Math.min(3, this.scale * factor));
      const after = this.screenToWorld(mx, my);
      this.panX += (after.x - before.x) * this.scale;
      this.panY += (after.y - before.y) * this.scale;
      this.render();
    }, { passive:false });

    this.svg.addEventListener('mousedown', (e) => {
      const rect = this.svg.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;

      // middle mouse or space/pan tool => pan
      if (e.button === 1 || this.tool === 'pan' || e.altKey) {
        isPanning = true; startX = mx; startY = my;
        startPanX = this.panX; startPanY = this.panY;
        this.svg.style.cursor = 'grabbing';
        e.preventDefault(); return;
      }

      if (this.tool === 'easydraw') {
        const w = this.screenToWorld(mx, my);
        this.easyDrawState = { startX:w.x, startY:w.y, curX:w.x, curY:w.y, paneId:this._paneAt(w.x,w.y) };
        return;
      }

      if (this.tool === 'eraseBar') {
        const w = this.screenToWorld(mx, my);
        this._eraseBarAt(w.x, w.y);
        return;
      }

      // select / split
      const w = this.screenToWorld(mx, my);
      const paneId = this._paneAt(w.x, w.y);
      if (!paneId) return;
      if (this.tool === 'select') {
        this.selectedPaneId = paneId;
        this.onSelect(paneId);
        this.render();
      } else if (this.tool === 'vsplit' || this.tool === 'hsplit') {
        // compute exact mm position within the pane and open the placement popup
        const axis = this.tool === 'vsplit' ? 'v' : 'h';
        const info = this._memberPosAt(paneId, axis, w.x, w.y);
        if (info) {
          this.selectedPaneId = paneId;
          this._memberGhost = { paneId, axis, pos: info.pos };
          this.render();
          if (this.onMemberPlace) {
            this.onMemberPlace({ paneId, axis, pos: info.pos,
              min: info.min, max: info.max, screenX: mx, screenY: my });
          }
        }
      } else if (this.tool === 'merge') {
        this.model.mergePane(paneId);
        this.selectedPaneId = this.model.panes[0]?.id;
        this.onChange(); this.onSelect(this.selectedPaneId);
        this.render();
      }
    });

    window.addEventListener('mousemove', (e) => {
      const rect = this.svg.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      if (isPanning) {
        this.panX = startPanX + (mx - startX);
        this.panY = startPanY + (my - startY);
        this.render();
      } else if (this.easyDrawState) {
        const w = this.screenToWorld(mx, my);
        this.easyDrawState.curX = w.x;
        this.easyDrawState.curY = w.y;
        this._updatePreviewOnly();   // lightweight — no full re-render
      } else if (this.tool === 'eraseBar') {
        // ERASE mode: highlight the bar under the cursor before the user clicks
        const w = this.screenToWorld(mx, my);
        const hit = this._barAt(w.x, w.y);
        const next = hit ? { paneId: hit.pane.id, index: hit.index } : null;
        const prev = this._hoverBar;
        const changed = (!prev && next) || (prev && !next) ||
          (prev && next && (prev.paneId!==next.paneId || prev.index!==next.index));
        if (changed) { this._hoverBar = next; this.render(); }
      } else if (this.tool === 'vsplit' || this.tool === 'hsplit') {
        // live ghost line following the cursor inside the hovered pane
        const w = this.screenToWorld(mx, my);
        const paneId = this._paneAt(w.x, w.y);
        if (paneId) {
          const axis = this.tool === 'vsplit' ? 'v' : 'h';
          const info = this._memberPosAt(paneId, axis, w.x, w.y);
          if (info) { this._hoverGhost = { paneId, axis, pos: info.pos }; this._updateGhostOnly(); }
        } else if (this._hoverGhost) {
          this._hoverGhost = null; this._updateGhostOnly();
        }
      }
      
      // ── Tooltip Safety Guard ──
      // If tooltip is visible but mouse is far from last known position, hide it
      if (this._tooltipVisible && this._lastTooltipPosition) {
        const dx = e.clientX - this._lastTooltipPosition.x;
        const dy = e.clientY - this._lastTooltipPosition.y;
        const distance = Math.sqrt(dx*dx + dy*dy);
        // Hide if distance exceeds 60px (threshold for "moved away")
        if (distance > 60) {
          this._hideProfileTooltip();
        }
      }
    });

    window.addEventListener('mouseup', () => {
      if (isPanning) { isPanning = false;
        this.svg.style.cursor = this.tool==='pan'?'grab':'default'; }
      if (this.easyDrawState) { this._commitEasyDraw(); this.easyDrawState = null; this.render(); }
    });

    // ── SVG Canvas mouseleave: hide tooltip when mouse leaves canvas ──
    this.svg.addEventListener('mouseleave', () => {
      if (this._tooltipVisible) {
        this._hideProfileTooltip();
      }
      this._hoverRole = null;
      this._activeHighlightElement = null;
    });
  }

  // Compute the member position (mm from pane's left/bottom edge) at a world point.
  _memberPosAt(paneId, axis, wx, wy) {
    const p = this.model.panes.find(pp => pp.id === paneId);
    if (!p) return null;
    const W = this.model.width, H = this.model.height;
    const px1 = p.x*W, py1 = p.y*H, pw = p.w*W, ph = p.h*H;
    const MIN = 100, SNAP = 5;
    if (axis === 'v') {
      let pos = wx - px1;                 // mm from left edge
      pos = Math.round(pos/SNAP)*SNAP;
      pos = Math.max(MIN, Math.min(pw-MIN, pos));
      return { pos, min: MIN, max: Math.round(pw-MIN), span: pw };
    } else {
      // from bottom edge: bottom is py1+ph (y grows downward)
      let pos = (py1 + ph) - wy;          // mm from bottom edge
      pos = Math.round(pos/SNAP)*SNAP;
      pos = Math.max(MIN, Math.min(ph-MIN, pos));
      return { pos, min: MIN, max: Math.round(ph-MIN), span: ph };
    }
  }

  // Apply the pending member split at an exact mm position.
  commitMember(paneId, axis, posMm) {
    const nid = this.model.splitPaneAt(paneId, axis, posMm);
    this._memberGhost = null;
    if (nid) { this.selectedPaneId = nid; this.onChange(); this.onSelect(nid); }
    this.render();
    return nid;
  }
  cancelMember() { this._memberGhost = null; this.render(); }

  equalisePane(paneId, axis, n) {
    const ids = this.model.equalisePane(paneId, axis, n);
    this._memberGhost = null;
    if (ids.length) {
      this.selectedPaneId = ids[0];
      this.onChange();
      this.onSelect(ids[0]);
    }
    this.render();
    return ids;
  }

  _paneAt(wx, wy) {
    // wx,wy in mm relative to canvas origin; frame origin at (0,0)
    const W = this.model.width, H = this.model.height;
    for (const p of this.model.panes) {
      const px1 = p.x*W, py1 = p.y*H, px2 = (p.x+p.w)*W, py2 = (p.y+p.h)*H;
      if (wx>=px1 && wx<=px2 && wy>=py1 && wy<=py2) return p.id;
    }
    return null;
  }

  _eraseBarAt(wx, wy) {
    const hit = this._barAt(wx, wy);
    if (!hit) return;
    hit.pane.glazingBars.splice(hit.index, 1);
    this._hoverBar = null;
    this.onChange(); this.render();
  }

  // Find the glazing bar (if any) under a world point, without removing it.
  // Returns {pane, index} or null. Shared by hover-highlight and erase-on-click.
  _barAt(wx, wy) {
    const W = this.model.width, H = this.model.height, bar = this.model.frame.thickness;
    const tol = 30; // mm hit tolerance
    for (const p of this.model.panes) {
      if (!p.glazingBars || !p.glazingBars.length) continue;
      const px1 = p.x*W + bar, py1 = p.y*H + bar;
      const pw = p.w*W - 2*bar, ph = p.h*H - 2*bar;
      for (let i = p.glazingBars.length - 1; i >= 0; i--) {
        const gb = p.glazingBars[i];
        if (gb.type === 'vertical') {
          const gx = px1 + pw*gb.pos;
          if (Math.abs(wx - gx) < tol && wy >= py1 && wy <= py1+ph) return { pane:p, index:i };
        } else {
          const gy = py1 + ph*gb.pos;
          if (Math.abs(wy - gy) < tol && wx >= px1 && wx <= px1+pw) return { pane:p, index:i };
        }
      }
    }
    return null;
  }

  _commitEasyDraw() {
    // remove preview
    const prev = this.svg.querySelector('#easyPreview');
    if (prev) prev.remove();

    const s = this.easyDrawState;
    if (!s || !s.paneId) return;
    const dx = Math.abs(s.curX - s.startX), dy = Math.abs(s.curY - s.startY);
    if (dx < 12 && dy < 12) return;          // ignore tiny drags (12mm)

    const pane = this.model.panes.find(p => p.id === s.paneId);
    if (!pane) return;
    const W = this.model.width, H = this.model.height, bar = this.model.frame.thickness;
    const isVertical = dy > dx;               // vertical drag => vertical bar

    // glass aperture bounds inside this pane (in mm)
    const gx1 = pane.x*W + bar, gy1 = pane.y*H + bar;
    const gw  = pane.w*W - 2*bar, gh = pane.h*H - 2*bar;

    if (isVertical) {
      const localX = (this.snapVal(s.startX) - gx1) / gw;
      pane.glazingBars.push({ type:'vertical', pos: Math.max(0.05, Math.min(0.95, localX)), thickness: 18 });
    } else {
      const localY = (this.snapVal(s.startY) - gy1) / gh;
      pane.glazingBars.push({ type:'horizontal', pos: Math.max(0.05, Math.min(0.95, localY)), thickness: 18 });
    }
    this.onChange();
  }

  /* ----- render ----- */
  render() {
    const svg = this.svg;
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const rect = svg.getBoundingClientRect();
    this._renderGrid(rect);

    const W = this.model.width, H = this.model.height;
    const o = this.worldToScreen(0, 0);
    const bar = this.mmToPx(this.model.frame.thickness);
    const pxW = this.mmToPx(W), pxH = this.mmToPx(H);

    // ensure gradient/filter defs exist for realistic frame
    this._ensureDefs();

    // Real DXF CAD-profile cross-section paths, embedded per member as
    // they're drawn (see _embedDxfCrossSection/_frameBar). Invisible in
    // the base render (fill:none/stroke:none) — these are the exact
    // geometry source that _renderProfileHighlights() clones, never a
    // generic bounding box.
    this._profileGeomEls = {};
    this._dxfGeomLayer = document.createElementNS(SVGNS,'g');
    this._dxfGeomLayer.setAttribute('class','qs-dxf-geometry-layer');
    this._dxfGeomLayer.setAttribute('pointer-events','none');
    svg.appendChild(this._dxfGeomLayer);

    // drop shadow under the whole window
    const shadow = this._rect(o.x+4, o.y+6, pxW, pxH,
      { fill:'rgba(0,0,0,0.18)', stroke:'none', sw:0 });
    shadow.setAttribute('filter','url(#qsBlur)');
    svg.appendChild(shadow);

    const col = this.model.frame.color;
    const shape = this.model.shape || 'rectangle';

    if (shape === 'rectangle') {
      // ---- realistic beveled frame (4 mitred bars) ----
      this._frameBar(o.x,        o.y,        pxW, bar,  col, 'top',    this._effectiveMemberRole('head'), 'head');
      this._frameBar(o.x,        o.y+pxH-bar,pxW, bar,  col, 'bottom', this._effectiveMemberRole('cill'), 'cill');
      this._frameBar(o.x,        o.y,        bar, pxH,  col, 'left',   this._effectiveMemberRole('jamb'), 'jamb');
      this._frameBar(o.x+pxW-bar,o.y,        bar, pxH,  col, 'right',  this._effectiveMemberRole('jamb'), 'jamb');
      const inner = this._rect(o.x+bar, o.y+bar, pxW-2*bar, pxH-2*bar,
        { fill:'none', stroke:'rgba(0,0,0,0.25)', sw:1 });
      svg.appendChild(inner);

      // invisible wider hit-target along the inner aperture line so the
      // glazing bead is directly clickable (its true bar is thin).
      const gbHit = this._rect(o.x+bar, o.y+bar, pxW-2*bar, pxH-2*bar,
        { fill:'none', stroke:'transparent', sw: Math.max(10, bar*0.6) });
      gbHit.setAttribute('pointer-events','stroke');
      gbHit.setAttribute('data-qs-clickable-part','glazing_bead');
      gbHit.style.cursor = 'pointer';
      gbHit.addEventListener('click', (evt) => this._handleSectionClick('glazing_bead', evt));
      svg.appendChild(gbHit);

      // staff bead: a second inner moulding line just inside the frame
      if (this.model.frame.staffBead) {
        const sb = Math.max(2, bar*0.22);
        const bead = this._rect(o.x+bar+sb, o.y+bar+sb,
          pxW-2*(bar+sb), pxH-2*(bar+sb),
          { fill:'none', stroke:'rgba(255,255,255,0.35)', sw:1.2 });
        bead.setAttribute('pointer-events','none');
        svg.appendChild(bead);
        const beadSh = this._rect(o.x+bar+sb+1, o.y+bar+sb+1,
          pxW-2*(bar+sb)-2, pxH-2*(bar+sb)-2,
          { fill:'none', stroke:'rgba(0,0,0,0.18)', sw:0.8 });
        beadSh.setAttribute('pointer-events','none');
        svg.appendChild(beadSh);
      }

      // panes (clipped to rectangle automatically)
      for (const p of this.model.panes) this._renderPane(p, o, W, H, bar);
      this._renderMullions(o, W, H, bar);
    } else {
      // ---- shaped frame (arched / gothic / circular) ----
      this._renderShapedFrame(o, W, H, bar, col, shape);
    }

    // door extras (sidelights / fanlight) overlay on top for doors
    if (this.model.unitType === 'door') this._renderDoorExtras(o, W, H, bar, col);

    // projecting cill (below the unit, wider than the frame)
    if (this.model.frame.cill) {
      const cillH = this.mmToPx(30), lip = this.mmToPx(40);
      const cy = o.y + pxH;
      const c = this._rect(o.x - lip, cy, pxW + lip*2, cillH,
        { fill: col, stroke:'rgba(0,0,0,0.35)', sw: 1 });
      svg.appendChild(c);
      const cb = this._rect(o.x - lip, cy, pxW + lip*2, cillH,
        { fill:'url(#qsFrameH)', stroke:'none', sw:0 });
      cb.setAttribute('pointer-events','none');
      svg.appendChild(cb);
      // end nose lines
      svg.appendChild(this._rect(o.x - lip, cy + cillH*0.7, pxW + lip*2, cillH*0.3,
        { fill:'rgba(0,0,0,0.15)', stroke:'none', sw:0 }));
      // end caps
      for (const ex of [o.x - lip, o.x + pxW + lip - 2]) {
        svg.appendChild(this._rect(ex, cy, 2, cillH,
          { fill:'rgba(0,0,0,0.28)', stroke:'none', sw:0 }));
      }
    }

    // member placement ghost (committed-pending or hover)
    const ghost = this._memberGhost || this._hoverGhost;
    if (ghost) this._renderMemberGhost(ghost, o, W, H);

    // dimensions
    this._renderDims(o, W, H);

    // easy-draw preview line
    if (this.easyDrawState) this._renderEasyDrawPreview();

    // CAD profile location overlay (glowing edge highlights) — rendered
    // LAST so it paints above every other layer: grid, frame bars, panes,
    // glass, dims, everything.
    this._renderProfileHighlights(o, W, H, bar);
  }

  _renderGrid(rect) {
    const g = document.createElementNS(SVGNS,'g');
    const step = this.mmToPx(this.grid);
    if (step > 4) {
      const ox = this.panX % step, oy = this.panY % step;
      for (let x = ox; x < rect.width; x += step) {
        const l = document.createElementNS(SVGNS,'line');
        l.setAttribute('x1',x); l.setAttribute('y1',0);
        l.setAttribute('x2',x); l.setAttribute('y2',rect.height);
        l.setAttribute('stroke','#e8e4da'); l.setAttribute('stroke-width', '1');
        g.appendChild(l);
      }
      for (let y = oy; y < rect.height; y += step) {
        const l = document.createElementNS(SVGNS,'line');
        l.setAttribute('x1',0); l.setAttribute('y1',y);
        l.setAttribute('x2',rect.width); l.setAttribute('y2',y);
        l.setAttribute('stroke','#e8e4da'); l.setAttribute('stroke-width','1');
        g.appendChild(l);
      }
    }
    this.svg.appendChild(g);
  }

  _renderPane(p, o, W, H, bar) {
    // Per-edge inset: full frame bar on outer edges, half the mullion width
    // on internal (shared) edges — so glass/panels meet the mullion with no gap.
    const mb   = bar * 0.6;          // mullion width (must match _renderMullions)
    const half = mb / 2;
    const eps  = 0.001;
    const insL = (p.x <= eps)             ? bar : half;
    const insT = (p.y <= eps)             ? bar : half;
    const insR = (p.x + p.w >= 1 - eps)   ? bar : half;
    const insB = (p.y + p.h >= 1 - eps)   ? bar : half;

    const x = o.x + this.mmToPx(p.x*W) + insL;
    const y = o.y + this.mmToPx(p.y*H) + insT;
    const w = this.mmToPx(p.w*W) - insL - insR;
    const h = this.mmToPx(p.h*H) - insT - insB;
    if (w <= 0 || h <= 0) return;

    const selected = p.id === this.selectedPaneId;

    // ── Solid door panel (infill === 'panel') ──
    if (p.infill === 'panel') {
      const panel = this._rect(x, y, w, h, {
        fill: selected ? '#B5651D' : (this.model.frame.color || '#8a5a2b'),
        stroke: selected ? '#C97B3D' : 'rgba(0,0,0,0.35)',
        sw: selected ? 2.5 : 1,
      });
      panel.style.cursor = 'pointer';
      this.svg.appendChild(panel);
      // raised-panel bevel: inset rectangle
      const inset = Math.min(w, h) * 0.12;
      if (w - 2*inset > 4 && h - 2*inset > 4) {
        const raised = this._rect(x+inset, y+inset, w-2*inset, h-2*inset, {
          fill: 'rgba(255,255,255,0.06)',
          stroke: 'rgba(0,0,0,0.25)', sw: 1.2,
        });
        raised.style.pointerEvents = 'none';
        this.svg.appendChild(raised);
      }

      this._renderOpener(p, x, y, w, h);
      return;
    }

    // ── SASH FRAME on opening panes (the physical opening leaf) ──
    // Fixed panes are direct-glazed; anything that opens gets a visible sash
    // sitting in the outer frame with a shadow gap — like real fabricated units.
    let gx = x, gy = y, gw = w, gh = h;   // final glass rect (inside sash if present)
    const hasSash = p.opening && p.opening !== 'Fixed';
    if (hasSash) {
      const sashPx = Math.min(this.mmToPx(52), Math.min(w, h) * 0.18);
      const flush  = !!this.model.frame.flushSash;
      // shadow gap between outer frame and sash (skipped for flush sash)
      if (!flush) {
        const gap = this._rect(x, y, w, h, { fill:'rgba(0,0,0,0.30)', stroke:'none', sw:0 });
        gap.setAttribute('pointer-events','none');
        this.svg.appendChild(gap);
        const inset = Math.max(1.5, this.mmToPx(6));
        gx = x + inset; gy = y + inset; gw = w - 2*inset; gh = h - 2*inset;
      }
      // sash bars (mitred, bevelled, woodgrained like the frame)
      // Framepoint-style: sash can carry its own finish, separate from the frame
      const col = this.model.frame.sashColor || this.model.frame.color;
      const sashRole = (this.model.profileRoles || {}).sash ? 'sash' : null;
      this._frameBar(gx,            gy,             gw,      sashPx, col, 'top',    sashRole, 'sash');
      this._frameBar(gx,            gy+gh-sashPx,   gw,      sashPx, col, 'bottom', sashRole, 'sash');
      this._frameBar(gx,            gy,             sashPx,  gh,     col, 'left',   sashRole, 'sash');
      this._frameBar(gx+gw-sashPx,  gy,             sashPx,  gh,     col, 'right',  sashRole, 'sash');
      gx += sashPx; gy += sashPx; gw -= 2*sashPx; gh -= 2*sashPx;
      if (gw <= 0 || gh <= 0) { this._renderOpener(p, x, y, w, h); return; }
    }

    // glass with photoreal sky gradient
    const glass = this._rect(gx, gy, gw, gh, {
      fill: selected ? 'url(#qsGlassSkySel)' : 'url(#qsGlassSky)',
      stroke: selected ? '#C97B3D' : '#9fb4bd',
      sw: selected ? 2.5 : 1,
    });
    glass.style.cursor = 'pointer';
    if (!selected) {
      glass.addEventListener('mouseenter', ()=>{ glass.setAttribute('stroke','#C97B3D'); glass.setAttribute('stroke-width','1.8'); });
      glass.addEventListener('mouseleave', ()=>{ glass.setAttribute('stroke','#9fb4bd'); glass.setAttribute('stroke-width','1'); });
    }
    this.svg.appendChild(glass);

    // glazing bead chamfer: light catches top/left, shadow on bottom/right
    const mkLine=(x1,y1,x2,y2,stroke,sw)=>{
      const l=document.createElementNS(SVGNS,'line');
      l.setAttribute('x1',x1);l.setAttribute('y1',y1);
      l.setAttribute('x2',x2);l.setAttribute('y2',y2);
      l.setAttribute('stroke',stroke);l.setAttribute('stroke-width',sw);
      l.setAttribute('pointer-events','none');
      this.svg.appendChild(l);
    };
    mkLine(gx+1, gy+1, gx+gw-1, gy+1, 'rgba(255,255,255,0.30)', 1.5);   // top
    mkLine(gx+1, gy+1, gx+1, gy+gh-1, 'rgba(255,255,255,0.22)', 1.5);   // left
    mkLine(gx+1, gy+gh-1, gx+gw-1, gy+gh-1, 'rgba(0,0,0,0.45)', 1.5);   // bottom
    mkLine(gx+gw-1, gy+1, gx+gw-1, gy+gh-1, 'rgba(0,0,0,0.35)', 1.5);   // right

    // top reflection sheen — light falls onto the glass from above
    const shade = this._rect(gx, gy, gw, Math.min(gh*0.22, this.mmToPx(90)),
      { fill:'url(#qsGlassShade)', stroke:'none', sw:0 });
    shade.setAttribute('pointer-events','none');
    this.svg.appendChild(shade);

    // glass reflection stripe
    const refl = document.createElementNS(SVGNS,'polygon');
    const rx = gx + gw*0.12, rw = gw*0.22;
    refl.setAttribute('points',
      `${rx},${gy} ${rx+rw},${gy} ${rx+rw-gw*0.1},${gy+gh} ${rx-gw*0.1},${gy+gh}`);
    refl.setAttribute('fill','rgba(255,255,255,0.10)');
    refl.setAttribute('pointer-events','none');
    this.svg.appendChild(refl);

    // obscure / privacy glass texture (any texture other than Clear)
    if (p.texture && p.texture !== 'Clear') {
      const ob = this._rect(gx, gy, gw, gh, { fill:'url(#qsObscure)', stroke:'none', sw:0 });
      ob.setAttribute('pointer-events','none');
      this.svg.appendChild(ob);
    }

    // leaded glass overlay (diamond or square lead cames)
    if (p.leaded && p.leaded !== 'none') this._renderLeaded(p, gx, gy, gw, gh);

    // glazing bars (duplex look: bar + shadow edge), inside the sash glass
    (p.glazingBars||[]).forEach((gb, gbIdx) => {
      const t = this.mmToPx(gb.thickness);
      const isHover = this._hoverBar && this._hoverBar.paneId===p.id && this._hoverBar.index===gbIdx;
      const barFill = isHover ? '#C0554A' : this.model.frame.color;
      if (gb.type === 'vertical') {
        const bx = gx + gw*gb.pos;
        const r=this._rect(bx-t/2, gy, t, gh,
          { fill:barFill, stroke:isHover?'#8A382F':'rgba(0,0,0,0.3)', sw:isHover?1.5:0.6 });
        this.svg.appendChild(r);
        const hl=this._rect(bx-t/2, gy, t*0.35, gh, { fill:'rgba(255,255,255,0.25)', stroke:'none', sw:0 });
        hl.setAttribute('pointer-events','none'); this.svg.appendChild(hl);
      } else {
        const by = gy + gh*gb.pos;
        const r=this._rect(gx, by-t/2, gw, t,
          { fill:barFill, stroke:isHover?'#8A382F':'rgba(0,0,0,0.3)', sw:isHover?1.5:0.6 });
        this.svg.appendChild(r);
        const hl=this._rect(gx, by-t/2, gw, t*0.35, { fill:'rgba(255,255,255,0.25)', stroke:'none', sw:0 });
        hl.setAttribute('pointer-events','none'); this.svg.appendChild(hl);
      }
    });

    // opener symbol
    this._renderOpener(p, x, y, w, h);
  }

  _renderOpener(p, x, y, w, h) {
    if (!p.opening || p.opening === 'Fixed') return;
    const cx = x+w/2, cy = y+h/2;
    const g = document.createElementNS(SVGNS,'g');
    g.setAttribute('stroke','#5b6b80');
    g.setAttribute('stroke-width','1.3');
    g.setAttribute('fill','none');
    g.setAttribute('stroke-dasharray','6,4');
    g.setAttribute('pointer-events','none');
    const line = (x1,y1,x2,y2)=>{
      const l=document.createElementNS(SVGNS,'line');
      l.setAttribute('x1',x1);l.setAttribute('y1',y1);
      l.setAttribute('x2',x2);l.setAttribute('y2',y2);g.appendChild(l);
    };
    const op = p.opening;
    // UK convention: dashed lines converge on the HINGE side
    if (op.includes('Top')||op==='Bottom Hung') { line(x,y+h,cx,y+h*0.12);line(x+w,y+h,cx,y+h*0.12); }
    else if (op.includes('Left')||op==='Casement') { line(x+w,y,x+w*0.12,cy);line(x+w,y+h,x+w*0.12,cy); }
    else if (op.includes('Right')) { line(x,y,x+w*0.88,cy);line(x,y+h,x+w*0.88,cy); }
    else if (op.includes('Tilt')) { line(x,y+h,cx,y+h*0.12);line(x+w,y+h,cx,y+h*0.12);line(x+w,y,x+w*0.12,cy); }
    else if (op.includes('Slid')) {
      line(x+w*0.15,cy,x+w*0.85,cy);
      const a=document.createElementNS(SVGNS,'polyline');
      a.setAttribute('points',`${x+w*0.3},${cy-h*0.05} ${x+w*0.18},${cy} ${x+w*0.3},${cy+h*0.05}`);
      g.appendChild(a);
      const b=document.createElementNS(SVGNS,'polyline');
      b.setAttribute('points',`${x+w*0.7},${cy-h*0.05} ${x+w*0.82},${cy} ${x+w*0.7},${cy+h*0.05}`);
      g.appendChild(b);
    }
    this.svg.appendChild(g);

    // ── realistic handle on the operating side (opposite the hinge) ──
    this._renderHandle(p, x, y, w, h);

    // ── sash horns (traditional detail on vertical sliders) ──
    if (this.model.frame.sashHorns && op === 'Sliding' && p.y <= 0.001) {
      const hy = y + h;                 // meeting rail of the top sash
      const hw = Math.max(3, w*0.02), hh = Math.min(14, h*0.10);
      for (const hx of [x + w*0.06, x + w*0.94 - hw]) {
        const horn = document.createElementNS(SVGNS,'path');
        horn.setAttribute('d',
          `M${hx} ${hy} L${hx} ${hy+hh*0.6} Q${hx} ${hy+hh} ${hx+hw} ${hy+hh*0.6} L${hx+hw} ${hy} Z`);
        horn.setAttribute('fill', this.model.frame.color);
        horn.setAttribute('stroke','rgba(0,0,0,0.3)');
        horn.setAttribute('stroke-width','0.8');
        horn.setAttribute('pointer-events','none');
        this.svg.appendChild(horn);
      }
    }
  }

  // Espagnolette-style handle: rosette + lever, coloured per frame.handleColor
  _renderHandle(p, x, y, w, h) {
    const op = p.opening || '';
    if (op === 'Fixed' || op.includes('Slid')) return;
    let hx, hy, vertical = true;
    if (op.includes('Left'))       { hx = x + w - Math.min(14, w*0.08); hy = y + h/2; }
    else if (op.includes('Right')) { hx = x + Math.min(14, w*0.08);     hy = y + h/2; }
    else if (op.includes('Top')||op.includes('Tilt')) { hx = x + w/2; hy = y + h - Math.min(14, h*0.08); vertical = false; }
    else if (op === 'Bottom Hung') { hx = x + w/2; hy = y + Math.min(14, h*0.08); vertical = false; }
    else if (op === 'French' || op === 'Casement') { hx = x + w - Math.min(14, w*0.08); hy = y + h/2; }
    else return;
    const s = Math.max(6, Math.min(w, h) * 0.055);        // handle size scale
    const fill = this._handleFill();
    const type = this.model.frame.handleType || 'lever';
    const g = document.createElementNS(SVGNS,'g');
    g.setAttribute('pointer-events','none');
    const stroke = 'rgba(0,0,0,0.35)';

    const rect = (rx, ry, rw, rh, round) => {
      const e = document.createElementNS(SVGNS,'rect');
      e.setAttribute('x', rx); e.setAttribute('y', ry);
      e.setAttribute('width', rw); e.setAttribute('height', rh);
      if (round != null) e.setAttribute('rx', round);
      e.setAttribute('fill', fill); e.setAttribute('stroke', stroke);
      e.setAttribute('stroke-width','0.7'); g.appendChild(e); return e;
    };
    const circ = (cx, cy, r, f) => {
      const e = document.createElementNS(SVGNS,'circle');
      e.setAttribute('cx', cx); e.setAttribute('cy', cy); e.setAttribute('r', r);
      e.setAttribute('fill', f||fill); e.setAttribute('stroke', stroke);
      e.setAttribute('stroke-width','0.7'); g.appendChild(e); return e;
    };
    const path = (d, f) => {
      const e = document.createElementNS(SVGNS,'path');
      e.setAttribute('d', d); e.setAttribute('fill', f||fill);
      e.setAttribute('stroke', stroke); e.setAttribute('stroke-width','0.7');
      g.appendChild(e); return e;
    };

    // backplate / rosette common to lever-style handles
    if (type === 'lever' || type === 'monkeytail' || type === 'cockspur') {
      rect(hx - s*0.35, hy - s*0.8, s*0.7, s*1.6, s*0.3);
    }

    if (type === 'lever') {
      if (vertical) rect(hx - s*0.22, hy - s*0.15, s*0.44, s*2.1, s*0.22);
      else          rect(hx - s*2.1 + s*0.44, hy - s*0.22, s*2.1, s*0.44, s*0.22);
    }
    else if (type === 'monkeytail') {
      // straight lever that curls into a scroll at the tip (heritage)
      if (vertical) {
        path(`M${hx-s*0.18} ${hy} L${hx-s*0.18} ${hy+s*1.7} `+
             `Q${hx-s*0.18} ${hy+s*2.3} ${hx+s*0.5} ${hy+s*2.2} `+
             `Q${hx+s*0.95} ${hy+s*2.1} ${hx+s*0.55} ${hy+s*1.7} `+
             `Q${hx+s*0.3} ${hy+s*1.55} ${hx+s*0.18} ${hy+s*1.75} `+
             `L${hx+s*0.18} ${hy} Z`);
      } else {
        path(`M${hx} ${hy-s*0.18} L${hx-s*1.7} ${hy-s*0.18} `+
             `Q${hx-s*2.3} ${hy-s*0.18} ${hx-s*2.2} ${hy+s*0.5} `+
             `Q${hx-s*2.1} ${hy+s*0.95} ${hx-s*1.7} ${hy+s*0.55} `+
             `Q${hx-s*1.55} ${hy+s*0.3} ${hx-s*1.75} ${hy+s*0.18} `+
             `L${hx} ${hy+s*0.18} Z`);
      }
    }
    else if (type === 'cockspur') {
      // small espagnolette pad handle with short down-turned lever
      if (vertical) rect(hx - s*0.25, hy - s*0.1, s*0.5, s*1.1, s*0.2);
      else          rect(hx - s*1.1, hy - s*0.25, s*1.1, s*0.5, s*0.2);
      circ(hx, hy, s*0.28, fill);
    }
    else if (type === 'tbar') {
      // door T-bar / pull handle: long bar on two standoffs
      const barLen = Math.min(h*0.5, s*7);
      rect(hx - s*0.22, hy - barLen/2, s*0.44, barLen, s*0.2);
      circ(hx, hy - barLen/2 + s*0.4, s*0.28);
      circ(hx, hy + barLen/2 - s*0.4, s*0.28);
    }
    else if (type === 'knob') {
      // centre door knob (teardrop) on a round rose
      circ(hx, hy, s*0.9, fill);
      circ(hx, hy, s*0.5, 'rgba(255,255,255,0.18)');
    }

    // spindle centre dot for lever families
    if (type === 'lever' || type === 'monkeytail' || type === 'cockspur') {
      circ(hx, hy, s*0.16, 'rgba(0,0,0,0.35)');
    }
    this.svg.appendChild(g);
  }

  _handleFill(){
    switch (this.model.frame.handleColor) {
      case 'black': return '#2A2C2E';
      case 'gold':  return '#C9A227';
      case 'white': return '#F2F2EE';
      default:      return 'url(#qsChrome)';
    }
  }

  // Lead cames overlay: 'diamond' (quarries) or 'square' grid, clipped to pane
  _renderLeaded(p, x, y, w, h) {
    const g = document.createElementNS(SVGNS,'g');
    g.setAttribute('stroke','#7d8489');
    g.setAttribute('stroke-width','1.6');
    g.setAttribute('pointer-events','none');
    const clipId = 'ld' + Math.random().toString(36).slice(2,8);
    const clip = document.createElementNS(SVGNS,'clipPath');
    clip.setAttribute('id', clipId);
    clip.appendChild(this._rect(x, y, w, h, { fill:'#fff' }));
    this.svg.appendChild(clip);
    g.setAttribute('clip-path', `url(#${clipId})`);
    const step = Math.max(this.mmToPx(140), 18);
    const line=(x1,y1,x2,y2)=>{const l=document.createElementNS(SVGNS,'line');
      l.setAttribute('x1',x1);l.setAttribute('y1',y1);l.setAttribute('x2',x2);l.setAttribute('y2',y2);g.appendChild(l);};
    if (p.leaded === 'diamond') {
      for (let d = -h; d < w + h; d += step) {
        line(x+d, y, x+d-h, y+h);      // "\" diagonals
        line(x+d, y, x+d+h, y+h);      // "/" diagonals
      }
    } else {
      for (let gx = x+step; gx < x+w; gx += step) line(gx, y, gx, y+h);
      for (let gy = y+step; gy < y+h; gy += step) line(x, gy, x+w, gy);
    }
    this.svg.appendChild(g);
  }

  _renderMullions(o, W, H, bar) {
    const col = this.model.frame.color;
    const mb = bar * (this.model.frame.slimMullionClip ? 0.32 : 0.6);
    const vEdges = _collectEdgeSpans(this.model.panes, 'v', W, H);
    const hEdges = _collectEdgeSpans(this.model.panes, 'h', W, H);
    const roles = this.model.profileRoles || {};
    const hRole = roles.transom ? 'transom' : (roles.coupler ? 'coupler' : null);
    for (const [rx, spans] of vEdges) {
      const mx = o.x + this.mmToPx(rx * W);
      for (const [y1, y2] of _mergeRanges(spans)) {
        this._frameBar(mx - mb/2, o.y + this.mmToPx(y1), mb, this.mmToPx(y2 - y1), col, 'left', roles.mullion ? 'mullion' : null, 'mullion');
      }
    }
    for (const [ty, spans] of hEdges) {
      const my = o.y + this.mmToPx(ty * H);
      for (const [x1, x2] of _mergeRanges(spans)) {
        this._frameBar(o.x + this.mmToPx(x1), my - mb/2, this.mmToPx(x2 - x1), mb, col, 'top', hRole, 'transom');
      }
    }
  }

  _renderDims(o, W, H) {
    const off = 28;
    const pxW = this.mmToPx(W), pxH = this.mmToPx(H);
    // ---- overall width (top, blue) ----
    this._dimLine(o.x, o.y-off, o.x+pxW, o.y-off, W, 'h', '#3E6FB0', 'W', 'overallW');
    // ---- overall height (right, blue) ----
    this._dimLine(o.x+pxW+off, o.y, o.x+pxW+off, o.y+pxH, H, 'v', '#3E6FB0', 'H', 'overallH');

    // ---- segment heights (left, green) : rows ----
    const rows = this._uniqueEdges(this.model.panes.map(p=>[p.y,p.y+p.h]));
    if (rows.length > 2) {
      for (let i=0;i<rows.length-1;i++){
        const y1=o.y+rows[i]*pxH, y2=o.y+rows[i+1]*pxH;
        const mm=Math.round((rows[i+1]-rows[i])*H);
        this._dimLine(o.x-off, y1, o.x-off, y2, mm, 'v', '#3D8B5C', 'rowH', 'row'+i);
      }
    }
    // ---- segment widths (bottom, green) : cols ----
    const cols = this._uniqueEdges(this.model.panes.map(p=>[p.x,p.x+p.w]));
    if (cols.length > 2) {
      for (let i=0;i<cols.length-1;i++){
        const x1=o.x+cols[i]*pxW, x2=o.x+cols[i+1]*pxW;
        const mm=Math.round((cols[i+1]-cols[i])*W);
        this._dimLine(x1, o.y+pxH+off, x2, o.y+pxH+off, mm, 'h', '#3D8B5C', 'colW', 'col'+i);
      }
    }
  }

  _uniqueEdges(pairs){
    const s=new Set([0,1]);
    pairs.forEach(([a,b])=>{ s.add(+a.toFixed(4)); s.add(+b.toFixed(4)); });
    return [...s].sort((a,b)=>a-b);
  }

  _dimLine(x1,y1,x2,y2,mmVal,dir,col,kind,key){
    const g=document.createElementNS(SVGNS,'g');
    const mk=(t,a,parent)=>{const e=document.createElementNS(SVGNS,t);for(const k in a)e.setAttribute(k,a[k]);(parent||g).appendChild(e);return e;};
    // dim line + ticks
    mk('line',{x1,y1,x2,y2,stroke:col,'stroke-width':1,'pointer-events':'none'});
    const tick=8;
    if(dir==='h'){mk('line',{x1,y1:y1-tick/2,x2:x1,y2:y1+tick/2,stroke:col,'stroke-width':1,'pointer-events':'none'});
      mk('line',{x1:x2,y1:y2-tick/2,x2,y2:y2+tick/2,stroke:col,'stroke-width':1,'pointer-events':'none'});}
    else{mk('line',{x1:x1-tick/2,y1,x2:x1+tick/2,y2:y1,stroke:col,'stroke-width':1,'pointer-events':'none'});
      mk('line',{x1:x2-tick/2,y1:y2,x2:x2+tick/2,y2,stroke:col,'stroke-width':1,'pointer-events':'none'});}
    const tx=(x1+x2)/2, ty=(y1+y2)/2;
    // editable pill: rounded rect + text, clickable
    const label = String(mmVal);
    const padX=6, boxW=Math.max(30, label.length*8+padX*2), boxH=18;
    const pill=document.createElementNS(SVGNS,'g');
    pill.style.cursor='pointer';
    pill.setAttribute('data-dimkind',kind);
    pill.setAttribute('data-dimkey',key);
    let bx=tx-boxW/2, by=ty-boxH/2;
    const rectA={x:bx,y:by,width:boxW,height:boxH,rx:4,fill:'#fff',stroke:col,'stroke-width':1.2};
    const txtA={x:tx,y:ty+4,fill:col,'font-size':12,'font-weight':600,'font-family':'IBM Plex Mono, monospace','text-anchor':'middle'};
    if(dir==='v'){
      pill.setAttribute('transform',`rotate(-90 ${tx} ${ty})`);
    }
    mk('rect',rectA,pill);
    const t=mk('text',txtA,pill); t.textContent=label;
    pill.addEventListener('click',(e)=>{ e.stopPropagation(); this._editDim(kind,key,mmVal,pill); });
    g.appendChild(pill);
    this.svg.appendChild(g);
  }

  _editDim(kind, key, current, pillEl){
    // Inline editable input overlaid at the pill's screen position (no blocking prompt)
    const wrap = this.svg.parentElement;
    if (!wrap) return;
    // remove any existing editor
    const existing = document.getElementById('qsDimEditor');
    if (existing) existing.remove();

    // find pill bounding box in page coords
    const pill = pillEl || (this._lastPill || null);
    let cx, cy;
    if (pill && pill.getBoundingClientRect) {
      const r = pill.getBoundingClientRect();
      const wr = wrap.getBoundingClientRect();
      cx = r.left - wr.left + r.width/2;
      cy = r.top  - wr.top  + r.height/2;
    } else {
      const wr = wrap.getBoundingClientRect();
      cx = wr.width/2; cy = wr.height/2;
    }

    const inp = document.createElement('input');
    inp.id = 'qsDimEditor';
    inp.type = 'number';
    inp.value = current;
    inp.style.cssText = `position:absolute;left:${cx-40}px;top:${cy-14}px;width:80px;
      height:28px;font-size:14px;font-family:'IBM Plex Mono',monospace;text-align:center;
      border:2px solid #C97B3D;border-radius:5px;z-index:100;background:#fff;color:#1B2430;
      box-shadow:0 4px 12px rgba(0,0,0,0.2);outline:none;`;
    // ensure wrapper is positioned
    if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
    wrap.appendChild(inp);
    inp.focus(); inp.select();

    const commit = () => {
      const mm = parseInt(inp.value, 10);
      inp.remove();
      if (!isNaN(mm) && mm >= 50) this._applyDimEdit(kind, key, mm);
    };
    const cancel = () => inp.remove();
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      else if (e.key === 'Escape') { e.preventDefault(); cancel(); }
    });
    inp.addEventListener('blur', commit);
  }

  _applyDimEdit(kind, key, mm){
    const W=this.model.width, H=this.model.height;
    if (kind==='W'){
      this.model.width = mm;
      const fW=document.getElementById('fW'); if(fW) fW.value=mm;
    }
    else if (kind==='H'){
      this.model.height = mm;
      const fH=document.getElementById('fH'); if(fH) fH.value=mm;
    }
    else if (kind==='colW' || kind==='rowH'){
      // resize a segment: adjust the panes on that band, redistribute the rest
      const axis = kind==='colW' ? 'x' : 'y';
      const dim  = kind==='colW' ? 'w' : 'h';
      const total = kind==='colW' ? W : H;
      const idx = parseInt(key.replace(/\D/g,''),10);
      const edges = this._uniqueEdges(this.model.panes.map(p=>[p[axis],p[axis]+p[dim]]));
      if (idx>=edges.length-1) return;
      // current segment fraction -> new fraction
      const newFrac = mm/total;
      const oldFrac = edges[idx+1]-edges[idx];
      const delta = newFrac - oldFrac;
      // shift all edges after idx by delta, then renormalise to keep 0..1
      const newEdges = edges.map((e,i)=> i<=idx ? e : e+delta);
      const span = newEdges[newEdges.length-1];
      const norm = newEdges.map(e=>e/span);
      // remap panes to new edges
      this.model.panes.forEach(p=>{
        const s=this._nearest(p[axis],edges), en=this._nearest(p[axis]+p[dim],edges);
        p[axis]=norm[s];
        p[dim]=Math.max(0.02, norm[Math.max(en,s+1)]-norm[s]);
      });
      // scale overall to keep the edited segment exact
      if (kind==='colW') this.model.width  = Math.round(total*span);
      else               this.model.height = Math.round(total*span);
    }
    this.fitView();
    if (this.onChange) this.onChange();
  }

  _nearest(v, edges){ let b=0,bd=1e9; edges.forEach((e,i)=>{const d=Math.abs(e-v);if(d<bd){bd=d;b=i;}}); return b; }

  _renderMemberGhost(g, o, W, H){
    const p = this.model.panes.find(pp => pp.id === g.paneId);
    if (!p) return;
    const px1 = p.x*W, py1 = p.y*H, pw = p.w*W, ph = p.h*H;
    const mk = (x1,y1,x2,y2) => {
      const l = document.createElementNS(SVGNS,'line');
      l.setAttribute('id','memberGhost');
      const a = this.worldToScreen(x1,y1), b = this.worldToScreen(x2,y2);
      l.setAttribute('x1',a.x); l.setAttribute('y1',a.y);
      l.setAttribute('x2',b.x); l.setAttribute('y2',b.y);
      l.setAttribute('stroke','#C97B3D'); l.setAttribute('stroke-width', Math.max(3, this.mmToPx(this.model.frame.thickness*0.6)));
      l.setAttribute('stroke-opacity','0.55'); l.setAttribute('stroke-dasharray','8,5');
      l.setAttribute('pointer-events','none');
      this.svg.appendChild(l);
    };
    let lblPt, lblTxt;
    if (g.axis === 'v') {
      const gx = px1 + g.pos;
      mk(gx, py1, gx, py1+ph);
      lblPt = this.worldToScreen(gx, py1+ph/2); lblTxt = `${Math.round(g.pos)}mm from left`;
    } else {
      const gy = (py1+ph) - g.pos;   // from bottom
      mk(px1, gy, px1+pw, gy);
      lblPt = this.worldToScreen(px1+pw/2, gy); lblTxt = `${Math.round(g.pos)}mm from bottom`;
    }
    // label chip
    const gLbl = document.createElementNS(SVGNS,'g');
    gLbl.setAttribute('id','memberGhostLbl');
    gLbl.setAttribute('pointer-events','none');
    const tw = lblTxt.length*6 + 12;
    const r = document.createElementNS(SVGNS,'rect');
    r.setAttribute('x',lblPt.x-tw/2); r.setAttribute('y',lblPt.y-9);
    r.setAttribute('width',tw); r.setAttribute('height',18); r.setAttribute('rx',3);
    r.setAttribute('fill','rgba(27,36,48,0.82)');
    gLbl.appendChild(r);
    const t = document.createElementNS(SVGNS,'text');
    t.setAttribute('x',lblPt.x); t.setAttribute('y',lblPt.y+4);
    t.setAttribute('fill','white'); t.setAttribute('font-size','10');
    t.setAttribute('font-family','IBM Plex Mono, monospace'); t.setAttribute('text-anchor','middle');
    t.textContent = lblTxt;
    gLbl.appendChild(t);
    this.svg.appendChild(gLbl);
  }

  _updateGhostOnly(){
    // remove existing ghost + label, redraw just those (fast, no full render)
    ['memberGhost','memberGhostLbl'].forEach(id=>{
      const e = this.svg.querySelector('#'+id); if (e) e.remove();
    });
    const g = this._hoverGhost || this._memberGhost;
    if (g) this._renderMemberGhost(g, this.worldToScreen(0,0), this.model.width, this.model.height);
  }

  _updatePreviewOnly(){
    // Remove any existing preview and draw just the preview line (fast)
    const old = this.svg.querySelector('#easyPreview');
    if (old) old.remove();
    const s = this.easyDrawState;
    if (!s) return;
    const a = this.worldToScreen(s.startX, s.startY);
    const b = this.worldToScreen(s.curX, s.curY);
    const dx = Math.abs(s.curX - s.startX), dy = Math.abs(s.curY - s.startY);
    const vertical = dy > dx;
    const l = document.createElementNS(SVGNS, 'line');
    l.setAttribute('id', 'easyPreview');
    if (vertical) { l.setAttribute('x1', a.x); l.setAttribute('y1', a.y); l.setAttribute('x2', a.x); l.setAttribute('y2', b.y); }
    else          { l.setAttribute('x1', a.x); l.setAttribute('y1', a.y); l.setAttribute('x2', b.x); l.setAttribute('y2', a.y); }
    l.setAttribute('stroke', '#C97B3D'); l.setAttribute('stroke-width', 3);
    l.setAttribute('stroke-dasharray', '6,3'); l.setAttribute('pointer-events', 'none');
    this.svg.appendChild(l);
  }

  _renderEasyDrawPreview(){
    const s=this.easyDrawState; if(!s)return;
    const a=this.worldToScreen(s.startX,s.startY);
    const b=this.worldToScreen(s.curX,s.curY);
    const dx=Math.abs(s.curX-s.startX),dy=Math.abs(s.curY-s.startY);
    const vertical=dy>dx;
    const l=document.createElementNS(SVGNS,'line');
    if(vertical){l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',a.x);l.setAttribute('y2',b.y);}
    else{l.setAttribute('x1',a.x);l.setAttribute('y1',a.y);l.setAttribute('x2',b.x);l.setAttribute('y2',a.y);}
    l.setAttribute('stroke','#C97B3D');l.setAttribute('stroke-width',3);
    l.setAttribute('stroke-dasharray','6,3');
    this.svg.appendChild(l);
  }

  // ---- shaped frame paths (arched / gothic / circular) ----
  // Build the outer path string in screen coords for a given shape.
  _shapePath(o, W, H, shape, inset) {
    // Geometry matches the reference prototype exactly.
    // inset=0 → outer frame edge; inset=barW → inner glass aperture edge.
    // Spring line position mirrors reference: sY = iB.y + iB.h (top of rectangular glass area).
    // In model y-up:  sY_outer = H - Math.round(barW*1.03)
    //                 sY_inner = H - Math.round(barW*1.03)  (same spring y)
    // In SVG y-down:  springY_px = o.y + Math.round(barW*1.03)*scale
    const barW = this.model.frame.thickness;
    const x0 = o.x + this.mmToPx(inset);
    const x1 = o.x + this.mmToPx(W - inset);               // right edge
    const y0 = o.y + this.mmToPx(inset);                   // top edge (SVG top)
    const y1 = o.y + this.mmToPx(H);                       // bottom edge (outer)
    const w  = x1 - x0;
    const cx = x0 + w / 2;
    // spring line = where the curved head meets the straight sides.
    // Driven by archRise (mm): how tall the curved head is. Falls back to a
    // sensible default (¼ of width, capped) when unset.
    const rise = Math.max(0, this.model.archRise != null
      ? this.model.archRise : Math.min(W * 0.25, 400));
    const risePx = this.mmToPx(rise);
    const springY = y0 + risePx;                           // spring in SVG y-down

    if (shape === 'circular') {
      const h  = y1 - y0;
      const ry = h / 2;
      const cy = y0 + ry;
      const rx = w / 2;
      // Two half-ellipses forming a full ellipse (SVG arc can't do 360° in one A command)
      return `M ${cx-rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx+rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx-rx} ${cy} Z`;
    }
    if (shape === 'arched') {
      // Semicircular/segmental arch head bulging UPWARD to the top edge.
      const archRy = springY - y0;                    // height of arch head
      const archRx = w / 2;
      // In SVG y-down, sweep-flag 1 bulges the arc UP toward y0 (the dome).
      return `M ${x0} ${y1} `                         // bottom-left
           + `L ${x0} ${springY} `                    // up to spring line
           + `A ${archRx} ${archRy} 0 0 1 ${x1} ${springY} ` // dome over the top
           + `L ${x1} ${y1} Z`;                       // down + close
    }
    if (shape === 'gothic') {
      // Gothic: two quadratic bezier curves meeting at an apex
      const archH  = springY - y0;                    // head height in px
      const apexY  = y0;                              // pointed apex at very top
      const riseF  = 0.6;                             // bezier handle factor (matches reference)
      const ctrlY  = apexY * riseF + springY * (1 - riseF);   // control point y
      return `M ${x0} ${y1} `
           + `L ${x0} ${springY} `
           + `Q ${x0} ${ctrlY} ${cx} ${apexY} `
           + `Q ${x1} ${ctrlY} ${x1} ${springY} `
           + `L ${x1} ${y1} Z`;
    }
    // rectangle fallback
    return `M ${x0} ${y0} L ${x1} ${y0} L ${x1} ${y1} L ${x0} ${y1} Z`;
  }

  _renderShapedFrame(o, W, H, bar, col, shape) {
    const svg = this.svg;
    const outerD = this._shapePath(o, W, H, shape, 0);
    const innerD = this._shapePath(o, W, H, shape, this.model.frame.thickness);
    // unique id per render so re-renders never reference a stale/removed clip
    const clipId = 'qsShapeClip_' + (this._shapeSeq = (this._shapeSeq||0) + 1);

    // clip defs FIRST (so glass can reference it)
    const defs = document.createElementNS(SVGNS, 'defs');
    const cp = document.createElementNS(SVGNS, 'clipPath');
    cp.id = clipId;
    const cpp = document.createElementNS(SVGNS, 'path');
    cpp.setAttribute('d', innerD);
    cp.appendChild(cpp);
    defs.appendChild(cp);
    svg.appendChild(defs);

    // glass fill backdrop clipped to the inner shape (so nothing shows outside)
    const glassGroup = document.createElementNS(SVGNS, 'g');
    glassGroup.setAttribute('clip-path', `url(#${clipId})`);
    // solid glass backdrop across whole aperture
    glassGroup.appendChild(this._rect(o.x, o.y, this.mmToPx(W), this.mmToPx(H),
      { fill:'url(#qsGlassSky)', stroke:'none', sw:0 }));
    for (const p of this.model.panes) {
      this._paneGlassEls(p, o, W, H, bar).forEach(e => glassGroup.appendChild(e));
    }
    svg.appendChild(glassGroup);

    // mullions clipped to the shape
    const mullGroup = document.createElementNS(SVGNS, 'g');
    mullGroup.setAttribute('clip-path', `url(#${clipId})`);
    this._renderMullionsInto(mullGroup, o, W, H, bar);
    svg.appendChild(mullGroup);

    // openers + handles clipped to shape (drawn on top of glass/mullions)
    const opGroup = document.createElementNS(SVGNS, 'g');
    opGroup.setAttribute('clip-path', `url(#${clipId})`);
    for (const p of this.model.panes) {
      if (p.infill === 'panel') continue;
      const b = this._paneBox(p, o, W, H, bar);
      if (b.w > 0 && b.h > 0) {
        // temporarily retarget svg to the clip group for opener/handle helpers
        const realSvg = this.svg; this.svg = opGroup;
        this._renderOpener(p, b.x, b.y, b.w, b.h);
        this.svg = realSvg;
      }
    }
    svg.appendChild(opGroup);

    // frame band LAST, on top: outer minus inner (evenodd) — closes the curve cleanly
    const frame = document.createElementNS(SVGNS, 'path');
    frame.setAttribute('d', outerD + ' ' + innerD);
    frame.setAttribute('fill-rule', 'evenodd');
    frame.setAttribute('fill', col);
    frame.setAttribute('stroke', 'rgba(0,0,0,0.4)');
    frame.setAttribute('stroke-width', '1.5');
    svg.appendChild(frame);

    // woodgrain over the frame band (timber) — also evenodd-clipped to the band
    if ((this.model.frame.material||'') === 'Timber') {
      const grain = document.createElementNS(SVGNS,'path');
      grain.setAttribute('d', outerD + ' ' + innerD);
      grain.setAttribute('fill-rule','evenodd');
      grain.setAttribute('fill','#000');
      grain.setAttribute('filter','url(#qsWoodV)');
      grain.setAttribute('pointer-events','none');
      svg.appendChild(grain);
    }

    // inner + outer outlines for crispness
    const io = document.createElementNS(SVGNS, 'path');
    io.setAttribute('d', innerD);
    io.setAttribute('fill', 'none');
    io.setAttribute('stroke', 'rgba(255,255,255,0.25)');
    io.setAttribute('stroke-width', '1');
    io.setAttribute('pointer-events','none');
    svg.appendChild(io);

    // projecting cill (curved shapes still sit on a straight cill board)
    if (this.model.frame.cill) {
      const cillH = this.mmToPx(30), lip = this.mmToPx(40);
      const cy = o.y + this.mmToPx(H);
      const pxW = this.mmToPx(W);
      svg.appendChild(this._rect(o.x - lip, cy, pxW + lip*2, cillH,
        { fill: col, stroke:'rgba(0,0,0,0.35)', sw:1 }));
      svg.appendChild(this._rect(o.x - lip, cy + cillH*0.7, pxW + lip*2, cillH*0.3,
        { fill:'rgba(0,0,0,0.15)', stroke:'none', sw:0 }));
    }
  }

  // pane glass box in px (shared by shaped opener placement)
  _paneBox(p, o, W, H, bar) {
    const mb = bar*0.6, half = mb/2, eps = 0.001;
    const insL = (p.x <= eps) ? bar : half;
    const insT = (p.y <= eps) ? bar : half;
    const insR = (p.x + p.w >= 1 - eps) ? bar : half;
    const insB = (p.y + p.h >= 1 - eps) ? bar : half;
    return {
      x: o.x + this.mmToPx(p.x*W) + insL,
      y: o.y + this.mmToPx(p.y*H) + insT,
      w: this.mmToPx(p.w*W) - insL - insR,
      h: this.mmToPx(p.h*H) - insT - insB,
    };
  }

  // Return glass + bar + opener elements for a pane (used by shaped clip group)
  _paneGlassEls(p, o, W, H, bar) {
    const els = [];
    const mb   = bar * 0.6;
    const half = mb / 2;
    const eps  = 0.001;
    const insL = (p.x <= eps)           ? bar : half;
    const insT = (p.y <= eps)           ? bar : half;
    const insR = (p.x + p.w >= 1 - eps) ? bar : half;
    const insB = (p.y + p.h >= 1 - eps) ? bar : half;
    const x = o.x + this.mmToPx(p.x*W) + insL;
    const y = o.y + this.mmToPx(p.y*H) + insT;
    const w = this.mmToPx(p.w*W) - insL - insR;
    const h = this.mmToPx(p.h*H) - insT - insB;
    if (w <= 0 || h <= 0) return els;
    const selected = p.id === this.selectedPaneId;
    if (p.infill === 'panel') {
      els.push(this._rect(x, y, w, h, {
        fill: selected ? '#B5651D' : (this.model.frame.color || '#8a5a2b'),
        stroke: selected ? '#C97B3D' : 'rgba(0,0,0,0.35)', sw: selected ? 2.5 : 1 }));
      const inset = Math.min(w, h) * 0.12;
      if (w-2*inset > 4 && h-2*inset > 4)
        els.push(this._rect(x+inset, y+inset, w-2*inset, h-2*inset, {
          fill:'rgba(255,255,255,0.06)', stroke:'rgba(0,0,0,0.25)', sw:1.2 }));
      return els;
    }
    els.push(this._rect(x, y, w, h, {
      fill: selected ? 'url(#qsGlassSkySel)' : 'url(#qsGlassSky)',
      stroke: selected ? '#C97B3D' : '#9fb4bd', sw: selected ? 2.5 : 1 }));
    for (const gb of (p.glazingBars||[])) {
      const t = this.mmToPx(gb.thickness);
      if (gb.type === 'vertical') els.push(this._rect(x+w*gb.pos-t/2, y, t, h, {fill:this.model.frame.color,sw:0}));
      else els.push(this._rect(x, y+h*gb.pos-t/2, w, t, {fill:this.model.frame.color,sw:0}));
    }
    return els;
  }

  _renderMullionsInto(group, o, W, H, bar) {
    const col = this.model.frame.color;
    const mb = bar * 0.6;
    const vEdges = _collectEdgeSpans(this.model.panes, 'v', W, H);
    const hEdges = _collectEdgeSpans(this.model.panes, 'h', W, H);
    for (const [rx, spans] of vEdges) {
      const mx = o.x + this.mmToPx(rx * W);
      for (const [y1, y2] of _mergeRanges(spans)) {
        group.appendChild(this._rect(mx - mb/2, o.y + this.mmToPx(y1), mb, this.mmToPx(y2 - y1),
          {fill:col, stroke:'rgba(0,0,0,0.3)', sw:0.5}));
      }
    }
    for (const [ty, spans] of hEdges) {
      const my = o.y + this.mmToPx(ty * H);
      for (const [x1, x2] of _mergeRanges(spans)) {
        group.appendChild(this._rect(o.x + this.mmToPx(x1), my - mb/2, this.mmToPx(x2 - x1), mb,
          {fill:col, stroke:'rgba(0,0,0,0.3)', sw:0.5}));
      }
    }
  }

  // ---- door extras: sidelights + fanlight dividers ----
  _renderDoorExtras(o, W, H, bar, col) {
    const d = this.model.door || {};
    const s = this.scale;
    // sidelight left
    if (d.slL > 0) {
      const x = o.x + this.mmToPx(d.slL);
      this.svg.appendChild(this._rect(x-bar*0.3, o.y+bar, bar*0.6, this.mmToPx(H)-2*bar, {fill:col,stroke:'rgba(0,0,0,0.3)',sw:0.5}));
    }
    if (d.slR > 0) {
      const x = o.x + this.mmToPx(W - d.slR);
      this.svg.appendChild(this._rect(x-bar*0.3, o.y+bar, bar*0.6, this.mmToPx(H)-2*bar, {fill:col,stroke:'rgba(0,0,0,0.3)',sw:0.5}));
    }
    // fanlight (horizontal divider near top)
    if (d.flH > 0) {
      const y = o.y + this.mmToPx(d.flH);
      this.svg.appendChild(this._rect(o.x+bar, y-bar*0.3, this.mmToPx(W)-2*bar, bar*0.6, {fill:col,stroke:'rgba(0,0,0,0.3)',sw:0.5}));
    }
    // double door meeting stile
    if (d.dtype === 'double' || d.leafCount === 2) {
      const cx = o.x + this.mmToPx(W/2);
      this.svg.appendChild(this._rect(cx-bar*0.4, o.y+bar, bar*0.8, this.mmToPx(H)-2*bar, {fill:col,stroke:'rgba(0,0,0,0.3)',sw:0.5}));
    }
  }

  _ensureDefs(){
    if (this.svg.querySelector('#qsDefs')) return;
    const defs = document.createElementNS(SVGNS,'defs');
    defs.id = 'qsDefs';
    defs.innerHTML = `
      <linearGradient id="qsFrameV" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="rgba(255,255,255,0.45)"/>
        <stop offset="18%" stop-color="rgba(255,255,255,0.12)"/>
        <stop offset="82%" stop-color="rgba(0,0,0,0.12)"/>
        <stop offset="100%" stop-color="rgba(0,0,0,0.35)"/>
      </linearGradient>
      <linearGradient id="qsFrameH" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(255,255,255,0.45)"/>
        <stop offset="18%" stop-color="rgba(255,255,255,0.12)"/>
        <stop offset="82%" stop-color="rgba(0,0,0,0.12)"/>
        <stop offset="100%" stop-color="rgba(0,0,0,0.35)"/>
      </linearGradient>
      <linearGradient id="qsGlassSky" x1="0" y1="0" x2="0.25" y2="1">
        <stop offset="0%"  stop-color="#3d4d5c"/>
        <stop offset="35%" stop-color="#2b3947"/>
        <stop offset="70%" stop-color="#1d2833"/>
        <stop offset="100%" stop-color="#141d27"/>
      </linearGradient>
      <linearGradient id="qsGlassSkySel" x1="0" y1="0" x2="0.25" y2="1">
        <stop offset="0%"  stop-color="#6b5138"/>
        <stop offset="55%" stop-color="#4a3826"/>
        <stop offset="100%" stop-color="#33261a"/>
      </linearGradient>
      <pattern id="qsObscure" width="7" height="7" patternUnits="userSpaceOnUse"
               patternTransform="rotate(35)">
        <rect width="7" height="7" fill="rgba(255,255,255,0.30)"/>
        <circle cx="2" cy="2" r="1.1" fill="rgba(255,255,255,0.55)"/>
        <circle cx="5.5" cy="5" r="0.9" fill="rgba(210,225,232,0.6)"/>
      </pattern>
      <linearGradient id="qsChrome" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#f2f5f7"/>
        <stop offset="45%" stop-color="#b9c1c8"/>
        <stop offset="55%" stop-color="#8f99a2"/>
        <stop offset="100%" stop-color="#dfe5e9"/>
      </linearGradient>
      <linearGradient id="qsGlassShade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="rgba(255,255,255,0.16)"/>
        <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
      </linearGradient>
      <linearGradient id="qsBrass" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#e8d48a"/>
        <stop offset="50%" stop-color="#b3922f"/>
        <stop offset="100%" stop-color="#d9c26e"/>
      </linearGradient>
      <filter id="qsWoodV" x="0%" y="0%" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.35 0.012" numOctaves="3" seed="7" result="n"/>
        <feColorMatrix in="n" type="matrix"
          values="0 0 0 0 0.28  0 0 0 0 0.17  0 0 0 0 0.06  0 0 0 0.55 0"/>
      </filter>
      <filter id="qsWoodH" x="0%" y="0%" width="100%" height="100%">
        <feTurbulence type="fractalNoise" baseFrequency="0.012 0.35" numOctaves="3" seed="7" result="n"/>
        <feColorMatrix in="n" type="matrix"
          values="0 0 0 0 0.28  0 0 0 0 0.17  0 0 0 0 0.06  0 0 0 0.55 0"/>
      </filter>
      <filter id="qsBlur" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="6"/>
      </filter>`;
    this.svg.appendChild(defs);
  }

  /* ── CAD Profile location overlay: highlight the frame edge(s) where an
     applied profile (role) lives. Colour-coded per role, glowing SVG
     strokes drawn on top of the frame. Persists while the Profiles tab
     is active (this.showProfileHighlights) and pulses on sidebar hover
     (this._pulseRole). ── */
  // Role → distinct theme color. Every individual CAD component keeps
  // its own unique, theme-harmonized color (never a shared/global bucket):
  //   Head (arch/curved)          → Royal Indigo
  //   Cill / Threshold            → Warm Bronze/Gold
  //   Mullion (vertical dividers) → Emerald Teal
  //   Transom/Coupler (horizontal)→ Soft Rose
  //   Jamb / Outer Frame          → Deep Slate Blue
  //   Glazing Bead                → Subtle Mint
  static PROFILE_HL_COLORS = {
    head:'#818CF8',
    outer_frame:'#38BDF8', jamb:'#38BDF8',
    cill:'#D97706', threshold:'#D97706',
    mullion:'#10B981',
    transom:'#FB7185', coupler:'#FB7185',
    glazing_bead:'#34D399'
  };
  static PROFILE_HL_FILLS = {
    head:'rgba(129, 140, 248, 0.08)',
    outer_frame:'rgba(56, 189, 248, 0.08)', jamb:'rgba(56, 189, 248, 0.08)',
    cill:'rgba(217, 119, 6, 0.08)', threshold:'rgba(217, 119, 6, 0.08)',
    mullion:'rgba(16, 185, 129, 0.08)',
    transom:'rgba(251, 113, 133, 0.08)', coupler:'rgba(251, 113, 133, 0.08)',
    glazing_bead:'rgba(52, 211, 153, 0.08)'
  };

  pulseProfileHighlight(role){ this._pulseRole = role; this.render(); }
  clearProfilePulse(){ this._pulseRole = null; this.render(); }

  // ── Interactive canvas deselection ──────────────────────────────────
  // Unassigns a CAD profile role from the current window and notifies the
  // host page (toast/save/sidebar refresh) via onProfileDeselect + onChange.
  _deselectProfile(role){
    if (!this.model.profileRoles || !(role in this.model.profileRoles)) return;
    const code = this.model.profileRoles[role];
    delete this.model.profileRoles[role];
    this._pulseRole = null;
    this._hoverRole = null;
    this._hideProfileTooltip();
    
    // Sync with sidebar: auto-scroll to card & flash highlight
    this._syncSidebarProfile(role, code);
    
    if (this.onProfileDeselect) this.onProfileDeselect(role);
    this.render();
    if (this.onChange) this.onChange();
  }

  // ── Sidebar Synchronization ──────────────────────────────────────
  // Auto-scroll the right sidebar to show the profile card and flash it
  _syncSidebarProfile(role, code){
    const sidebarPanel = document.querySelector('.dz-scroll');
    if (!sidebarPanel) return;

    // Find the profile card for this role+code
    const cards = sidebarPanel.querySelectorAll('.qs-prc');
    let targetCard = null;
    for (const card of cards) {
      const cardText = card.textContent || '';
      // Match by code and role proximity in the DOM
      if (cardText.includes(code)) {
        targetCard = card;
        break;
      }
    }

    if (targetCard) {
      // Scroll the sidebar to show this card
      targetCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // Flash the card with a brief red glow
      this._flashProfileCard(targetCard);
    }
  }

  // Flash a profile card with animated red glow & pulse
  _flashProfileCard(card){
    if (!card) return;
    const origBg = card.style.background || '';
    const origBorder = card.style.borderColor || '';
    
    // Apply flash styling
    card.style.transition = 'all 0.3s ease';
    card.style.background = 'rgba(220, 38, 38, 0.15)';
    card.style.borderColor = '#DC2626';
    card.style.boxShadow = '0 0 12px rgba(220, 38, 38, 0.4)';

    // Remove button highlight (if exists)
    const removeBtn = card.querySelector('.qs-removebtn');
    if (removeBtn) {
      removeBtn.style.background = '#DC2626';
      removeBtn.style.color = 'white';
      removeBtn.style.transform = 'scale(1.05)';
    }

    // Revert after 1.2s
    setTimeout(() => {
      card.style.background = origBg;
      card.style.borderColor = origBorder;
      card.style.boxShadow = '';
      card.style.transition = '';
      if (removeBtn) {
        removeBtn.style.background = '';
        removeBtn.style.color = '';
        removeBtn.style.transform = '';
      }
    }, 1200);
  }

  // When hovering canvas highlight — or after a canvas section click
  // (reverse workflow) — switch to the Profiles tab if needed, scroll the
  // right sidebar to the matching applied profile card, and mark it as
  // the active '✓ APPLIED' card with a glowing border.
  _scrollSidebarToRole(role){
    // Ensure the Profiles tab (where profile cards live) is showing.
    if (typeof window !== 'undefined' && window.currentTab !== 'profiles' && typeof window.setTab === 'function') {
      window.setTab('profiles');
    } else if (typeof window !== 'undefined' && typeof window.qsBuildProfs === 'function') {
      // Already on the profiles tab — just rebuild so the just-applied
      // profile's '✓ APPLIED' badge/card is present before we scroll.
      window.qsBuildProfs();
    }

    const sidebarPanel = document.querySelector('.dz-scroll');
    if (!sidebarPanel) return;

    const cards = sidebarPanel.querySelectorAll('.qs-prc');
    const windowRoles = this.model.profileRoles || {};
    const activeCode = windowRoles[role];

    let matchedCard = null;
    for (const card of cards) {
      const cardText = card.textContent || '';
      if (activeCode && cardText.includes(activeCode)) { matchedCard = card; break; }
    }
    if (!matchedCard) return;

    matchedCard.scrollIntoView({ behavior: 'smooth', block: 'center' });

    // Glowing '✓ APPLIED' emphasis on the matched card (in addition to
    // whatever static "APPLIED" styling qsBuildProfs already renders).
    matchedCard.classList.add('qs-prc-active', 'qs-prc-just-applied');
    matchedCard.style.boxShadow = '0 0 0 2px #22C55E, 0 0 14px rgba(34,197,94,0.65)';
    matchedCard.style.transition = 'box-shadow 0.2s ease';
    clearTimeout(this._sidebarGlowTimeout);
    this._sidebarGlowTimeout = setTimeout(() => {
      matchedCard.classList.remove('qs-prc-just-applied');
      matchedCard.style.boxShadow = '';
    }, 1600);
  }

  // Floating "Click to Deselect" badge, positioned next to the cursor.
  // Lives in the SVG's parent wrapper (not the SVG itself) so it survives
  // render() calls untouched.
  _showProfileTooltip(evt){
    const wrap = this.svg.parentElement;
    if (!wrap) return;
    
    // Clear any pending hide timeout
    this._tooltipTimeout && clearTimeout(this._tooltipTimeout);
    
    let tip = document.getElementById('qsProfileDeselectTip');
    if (!tip){
      tip = document.createElement('div');
      tip.id = 'qsProfileDeselectTip';
      tip.className = 'qs-profile-deselect-tip';
      tip.innerHTML = '<strong>✕ Click to Remove</strong><br><small>Removes profile immediately</small>';
      tip.style.fontSize = '11px';
      tip.style.lineHeight = '1.3';
      tip.style.textAlign = 'center';
      tip.style.transition = 'opacity 0.15s ease';
      if (getComputedStyle(wrap).position === 'static') wrap.style.position = 'relative';
      wrap.appendChild(tip);
    }
    tip.style.display = 'block';
    tip.style.visibility = 'visible';
    tip.style.opacity = '1';
    tip.setAttribute('data-visible', 'true');
    this._tooltipVisible = true;
    this._moveProfileTooltip(evt);
    
    // Safety timeout: auto-hide after 8 seconds if not interacted
    this._tooltipTimeout = setTimeout(() => {
      if (this._tooltipVisible) {
        this._hideProfileTooltip();
      }
    }, 8000);
  }
  
  _moveProfileTooltip(evt){
    const tip = document.getElementById('qsProfileDeselectTip');
    if (!tip || tip.getAttribute('data-visible') !== 'true') return;
    const wrap = this.svg.parentElement;
    if (!wrap) return;
    const wr = wrap.getBoundingClientRect();
    const x = evt.clientX - wr.left + 14;
    const y = evt.clientY - wr.top - 32;
    tip.style.left = x + 'px';
    tip.style.top = y + 'px';
    // Store position for safety distance check
    this._lastTooltipPosition = { x: evt.clientX, y: evt.clientY };
  }
  _hideProfileTooltip(){
    const tip = document.getElementById('qsProfileDeselectTip');
    if (tip) {
      tip.style.display = 'none';
      tip.style.visibility = 'hidden';
      tip.style.opacity = '0';
      tip.setAttribute('data-visible', 'false');
    }
    this._lastTooltipPosition = null;
    this._tooltipTimeout && clearTimeout(this._tooltipTimeout);
  }

  /* ── NOTE ──────────────────────────────────────────────────────────────
     The bounding-box/rect/polygon geometry calculators that used to live
     here (_profileHeadGeometry, _profileCillGeometry,
     _profileGlazingPerimeterGeometry, _profileFrameBandGeometry) have been
     removed. _renderProfileHighlights() now exclusively clones the real
     embedded DXF cross-section paths produced by _embedDxfCrossSection()
     — see _frameBar() — instead of computing generic bounding shapes. */

  // Paint one profile highlight by cloning the ACTUAL embedded DXF CAD
  // cross-section path element for this member (geom.el — see
  // _embedDxfCrossSection) — the exact stepped contour shown in the
  // sidebar profile card thumbnails, never a generic bounding box/rect/
  // line. Applies the required stroke-width:4px + fill-opacity:0.35.
  _paintProfileGeometry(g, geom, role){
    if (!geom || !geom.el) return; // no real DXF geometry embedded for this member — nothing to clone, no fallback shape drawn
    const strokeColor = DrawingCanvas.PROFILE_HL_COLORS[role] || '#38BDF8';
    const pulsing = this._pulseRole === role || this._hoverRole === role;

    const el = geom.el.cloneNode(true);
    el.setAttribute('fill', strokeColor);
    el.setAttribute('fill-opacity', 0.35);
    el.setAttribute('stroke', strokeColor);
    el.setAttribute('stroke-width', 4);
    el.setAttribute('stroke-linecap', 'round');
    el.setAttribute('stroke-linejoin', 'round');
    el.setAttribute('stroke-opacity', pulsing ? 1 : 0.95);
    el.setAttribute('class', `qs-profile-hl qs-profile-hl--${role}`);
    // Soft, non-blooming edge glow — the SVG/DOM equivalent of
    // ctx.shadowBlur = 6 / ctx.shadowColor = strokeColor. A single tight
    // drop-shadow (no wide halo) so the line lights up without blooming
    // and the ultra-translucent fill stays the dominant surface cue.
    el.style.filter = `drop-shadow(0 0 ${pulsing ? 4 : 3}px ${strokeColor})`;
    if (pulsing){
      const anim = document.createElementNS(SVGNS,'animate');
      anim.setAttribute('attributeName','stroke-opacity');
      anim.setAttribute('values','1;0.4;1');
      anim.setAttribute('dur','1s');
      anim.setAttribute('repeatCount','indefinite');
      el.appendChild(anim);
    }

    // Clickable deselect target — the group above carries pointer-events:none
    // so gaps between shapes still pass clicks through to panes underneath,
    // but each painted highlight explicitly re-enables events on itself.
    el.setAttribute('pointer-events', 'visiblePainted');
    el.style.cursor = 'pointer';
    el.addEventListener('mouseenter', (evt) => {
      this._hoverRole = role;
      this._activeHighlightElement = el;
      this._showProfileTooltip(evt);
      // Auto-scroll sidebar to show this profile's card
      this._scrollSidebarToRole(role);
      this.render();
    });
    el.addEventListener('mousemove', (evt) => { 
      this._moveProfileTooltip(evt);
    });
    el.addEventListener('mouseleave', (evt) => {
      this._hoverRole = null;
      this._activeHighlightElement = null;
      this._hideProfileTooltip();
      this.render();
    });
    el.addEventListener('click', (evt) => {
      evt.stopPropagation();
      // Immediate one-click removal: no sidebar interaction needed
      this._deselectProfile(role);
    });

    g.appendChild(el);
  }

  // Re-evaluated on every dc.render() call and on sidebar profile card
  // hover/focus (via pulseProfileHighlight/clearProfilePulse → render()).
  // STRICT DXF-ONLY MODE: every highlight is a clone of the actual traced
  // CAD profile cross-section path embedded into the canvas for that
  // member by _embedDxfCrossSection() during _frameBar() — the exact
  // stepped contour shown in the sidebar profile card thumbnails. There
  // is no bounding-box / rect / line fallback: a role only lights up
  // once real DXF geometry has been embedded for at least one of its
  // member bars.
  _renderProfileHighlights(o, W, H, bar){
    if (!this.showProfileHighlights) return;
    const roles = this.model.profileRoles || {};
    if (!Object.keys(roles).length) return;

    const g = document.createElementNS(SVGNS,'g');
    g.setAttribute('pointer-events','none');
    g.setAttribute('class','qs-profile-highlight-layer');

    const paintEmbeddedRole = (role) => {
      const els = this.svg.querySelectorAll(`[data-qs-part="${role}"]`);
      if (!els || !els.length) return;
      for (const el of els){
        this._paintProfileGeometry(g, { el }, role);
      }
    };

    // Outer frame perimeter — clones the actual embedded DXF cross-section
    // path for each outer-frame bar (top/bottom/left/right) that wasn't
    // overridden by a more specific head/cill/jamb assignment.
    if (roles.outer_frame) paintEmbeddedRole('outer_frame');

    // Head — clones the real traced head-bar DXF cross-section.
    if (roles.head) paintEmbeddedRole('head');

    // Cill — clones the real traced cill-bar DXF cross-section.
    if (roles.cill) paintEmbeddedRole('cill');

    // Jamb — clones the real traced jamb-bar DXF cross-section (both
    // left and right bars were embedded under this role).
    if (roles.jamb) paintEmbeddedRole('jamb');

    // Internal members — horizontal dividers are transom/coupler,
    // vertical dividers are mullion. Each clones its own embedded DXF
    // cross-section geometry, keeping its distinct theme colour.
    if (roles.transom) paintEmbeddedRole('transom');
    if (roles.coupler) paintEmbeddedRole('coupler');
    if (roles.mullion) paintEmbeddedRole('mullion');

    // Appended last within render() and re-appended here at the very end
    // of the stack (see render()) so it always paints above every other
    // element — grid, frame bars, panes, glass, dims, everything.
    this.svg.appendChild(g);
  }

  // Resolve which profileRoles key actually governs a given member:
  // a specific role (head/cill/jamb) wins when assigned, otherwise the
  // generic 'outer_frame' role is used as the fallback. Returns null
  // when neither is assigned (no DXF geometry to embed for this member).
  _effectiveMemberRole(specific){
    const roles = this.model.profileRoles || {};
    if (roles[specific]) return specific;
    if (roles.outer_frame) return 'outer_frame';
    return null;
  }

  // Look up the CAD profile (with its traced DXF svg_path) currently
  // assigned to a given member role.
  _lookupCadProfile(role){
    if (!role) return null;
    const roles = this.model.profileRoles || {};
    const code = roles[role];
    if (!code) return null;
    const list = (typeof CAD_PROFILES !== 'undefined' && Array.isArray(CAD_PROFILES))
      ? CAD_PROFILES
      : (this.cadProfiles || (typeof window !== 'undefined' ? window.CAD_PROFILES : null) || []);
    return list.find(p => p.code === code) || null;
  }

  // Embed the actual traced DXF cross-section path (profile.svg_path,
  // 200x200 viewBox) for this member into the SVG canvas, scaled to fit
  // the member's real on-screen footprint. Tagged with data-qs-part so
  // it can be identified/inspected, and kept invisible in the base render
  // (fill:none / stroke:none) — it exists purely as the geometry source
  // that _renderProfileHighlights() clones for the glowing highlight.
  // No embedding happens (and nothing is stored) when the assigned
  // profile has no traced geometry — callers must not fall back to a
  // bounding-box shape in that case.
  _embedDxfCrossSection(x, y, w, h, side, role){
    if (!role) return;
    const profile = this._lookupCadProfile(role);
    if (!profile || !profile.svg_path) return;

    const path = document.createElementNS(SVGNS, 'path');
    path.setAttribute('d', profile.svg_path);
    path.setAttribute('data-qs-part', role);
    path.setAttribute('data-qs-profile-code', profile.code || '');
    path.setAttribute('data-qs-side', side || '');
    // Map the profile's normalized 200x200 cross-section viewBox onto
    // this member's actual rendered rectangle (x, y, w, h).
    path.setAttribute('transform', `translate(${x},${y}) scale(${w/200},${h/200})`);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', 'none');
    path.setAttribute('pointer-events', 'none');

    if (this._dxfGeomLayer) this._dxfGeomLayer.appendChild(path);
    if (!this._profileGeomEls) this._profileGeomEls = {};
    if (!this._profileGeomEls[role]) this._profileGeomEls[role] = [];
    this._profileGeomEls[role].push(path);
  }

  // Draw a single frame bar with base colour + bevel gradient overlay.
  // When clickRole is given, the whole bar becomes clickable: a click
  // applies that role's default/active CAD profile and syncs the sidebar.
  _frameBar(x, y, w, h, col, side, role, clickRole){
    const bg = document.createElementNS(SVGNS,'g');
    bg.setAttribute('class','qs-frame-bar');
    if (clickRole){
      bg.setAttribute('data-qs-clickable-part', clickRole);
      bg.style.cursor = 'pointer';
      bg.addEventListener('click', (evt) => this._handleSectionClick(clickRole, evt));
    }

    // base colour
    const base = this._rect(x, y, w, h, { fill: col, stroke:'none', sw:0 });
    bg.appendChild(base);
    // procedural woodgrain for timber frames (feTurbulence — no images needed)
    if ((this.model.frame.material||'') === 'Timber') {
      const grain = this._rect(x, y, w, h, { fill:'#000', stroke:'none', sw:0 });
      grain.setAttribute('filter', (side==='left'||side==='right') ? 'url(#qsWoodV)' : 'url(#qsWoodH)');
      grain.setAttribute('pointer-events','none');
      bg.appendChild(grain);
    }
    // bevel gradient overlay (vertical bars use V gradient, horizontal use H)
    const grad = (side==='left'||side==='right') ? 'url(#qsFrameV)' : 'url(#qsFrameH)';
    const bevel = this._rect(x, y, w, h, { fill: grad, stroke:'none', sw:0 });
    bevel.setAttribute('pointer-events','none');
    bg.appendChild(bevel);
    // thin outline
    const line = this._rect(x, y, w, h, { fill:'none', stroke:'rgba(0,0,0,0.3)', sw:0.5 });
    line.setAttribute('pointer-events','none');
    bg.appendChild(line);

    this.svg.appendChild(bg);

    // Embed the real traced DXF cross-section geometry for this member
    // (if a CAD profile with geometry is assigned to its role) so the
    // profile highlight system has actual CAD geometry to clone instead
    // of falling back to this bar's bounding rectangle.
    this._embedDxfCrossSection(x, y, w, h, side, role);
  }

  // Canvas → sidebar reverse workflow: clicking a structural section
  // (Head/Jamb/Outer Frame/Mullion/Transom/Sash/Cill/Glazing Bead)
  // applies that role's default/active CAD profile, highlights it on the
  // canvas, and auto-scrolls + marks the matching sidebar card as applied.
  _handleSectionClick(clickRole, evt){
    if (!clickRole) return;
    if (evt){ evt.stopPropagation(); }

    if (typeof window !== 'undefined' && typeof window.qsApplyDefaultProfileForRole === 'function') {
      window.qsApplyDefaultProfileForRole(clickRole);
    } else {
      this._applyDefaultProfileForRole(clickRole);
    }

    // highlight the section on the canvas
    this.showProfileHighlights = true;
    this._pulseRole = clickRole;
    this._hoverRole = clickRole;
    this.render();

    // auto-scroll + sync the right sidebar to the applied profile card
    this._scrollSidebarToRole(clickRole);
  }

  // Fallback default-profile applier used when the host page hasn't
  // provided window.qsApplyDefaultProfileForRole. Applies the role's
  // is_role_default profile (or its first matching profile) directly to
  // the window model, keeping undo/redo + canvas sync intact via
  // this.onChange().
  _applyDefaultProfileForRole(role){
    const list = (typeof CAD_PROFILES !== 'undefined' && Array.isArray(CAD_PROFILES))
      ? CAD_PROFILES
      : (this.cadProfiles || (typeof window !== 'undefined' ? window.CAD_PROFILES : null) || []);
    if (!list || !list.length) return;

    const target = list.find(p => p.role === role && p.is_role_default)
                || list.find(p => p.role === role);
    if (!target) return;

    if (!this.model.profileRoles) this.model.profileRoles = {};
    if (this.model.profileRoles[role] === target.code) return; // already applied

    this.model.profileRoles[role] = target.code;
    if (typeof this.onChange === 'function') this.onChange();
  }

  _rect(x,y,w,h,s){
    const r=document.createElementNS(SVGNS,'rect');
    r.setAttribute('x',x);r.setAttribute('y',y);
    r.setAttribute('width',Math.max(0,w));r.setAttribute('height',Math.max(0,h));
    if(s.fill)r.setAttribute('fill',s.fill);
    if(s.stroke)r.setAttribute('stroke',s.stroke);
    if(s.sw!=null)r.setAttribute('stroke-width',s.sw);
    return r;
  }

  zoomIn(){ this.scale=Math.min(3,this.scale*1.15); this.render(); }
  zoomOut(){ this.scale=Math.max(0.05,this.scale*0.87); this.render(); }
  resetZoom(){ this.fitView(); }
}

/* ------------------------------------------------------------------
   Static unit renderer — produces a self-contained SVG string for a
   WindowModel (used by the Facade View + thumbnails). viewBox is in mm
   with a small padding, so callers can scale freely.
   ------------------------------------------------------------------ */
function renderUnitSVG(model, opts = {}) {
  const W = model.width, H = model.height, bar = model.frame.thickness;
  const col = model.frame.color || '#2B2F33';
  const shape = model.shape || 'rectangle';
  const pad = opts.pad != null ? opts.pad : 0;
  const vbW = W + pad*2, vbH = H + pad*2;
  const ox = pad, oy = pad;
  const glassFill = opts.glassFill || '#26313d';

  // helpers to build path strings in mm coords (y-down within the svg)
  function shapePath(inset) {
    // Matches _shapePath in DrawingCanvas — arch head driven by archRise (mm).
    const x0 = ox + inset, x1 = ox + W - inset;
    const y0 = oy + inset;                                 // top edge (SVG y-down)
    const y1 = oy + H;                                     // bottom edge (outer)
    const w  = x1 - x0;
    const cx = x0 + w / 2;
    const rise = Math.max(0, model.archRise != null
      ? model.archRise : Math.min(W * 0.25, 400));
    const springY = y0 + rise;                             // spring line (mm coords)

    if (shape === 'circular') {
      const h  = y1 - y0;
      const ry = h / 2, rx = w / 2;
      const cy = y0 + ry;
      return `M ${cx-rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx+rx} ${cy} A ${rx} ${ry} 0 1 0 ${cx-rx} ${cy} Z`;
    }
    if (shape === 'arched') {
      const archRy = springY - y0;
      const archRx = w / 2;
      // sweep 1 → dome bulges UP toward y0
      return `M ${x0} ${y1} L ${x0} ${springY} A ${archRx} ${archRy} 0 0 1 ${x1} ${springY} L ${x1} ${y1} Z`;
    }
    if (shape === 'gothic') {
      const ctrlY = y0 * 0.6 + springY * 0.4;
      return `M ${x0} ${y1} L ${x0} ${springY} Q ${x0} ${ctrlY} ${cx} ${y0} Q ${x1} ${ctrlY} ${x1} ${springY} L ${x1} ${y1} Z`;
    }
    return `M ${x0} ${y0} L ${x1} ${y0} L ${x1} ${y1} L ${x0} ${y1} Z`;
  }

  let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${vbW} ${vbH}" preserveAspectRatio="xMidYMid meet">`;
  const clipId = 'uc' + Math.random().toString(36).slice(2,7);

  if (shape === 'rectangle') {
    // glass fill
    s += `<rect x="${ox+bar}" y="${oy+bar}" width="${W-2*bar}" height="${H-2*bar}" fill="${glassFill}"/>`;

    // --- appearance helpers (string-emitting, mm coords) ---
    const handleHex = ({black:'#2A2C2E',gold:'#C9A227',white:'#F2F2EE'})[model.frame.handleColor] || '#c3ccd2';
    function opener(p, gx, gy, gw, gh){
      const op=p.opening||p.opener||'Fixed';
      if(!op||op==='Fixed'||op==='Fixed light') return '';
      const cx=gx+gw/2, cy=gy+gh/2, dash='stroke="#5b6b80" stroke-width="'+Math.max(2,bar*0.09)+'" stroke-dasharray="'+bar*0.4+','+bar*0.3+'" fill="none"';
      let d='';
      const L=(x1,y1,x2,y2)=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" ${dash}/>`;
      if(op.includes('Left')||op==='Casement'){ d+=L(gx+gw,gy,gx+gw*0.1,cy); d+=L(gx+gw,gy+gh,gx+gw*0.1,cy); }
      else if(op.includes('Right')){ d+=L(gx,gy,gx+gw*0.9,cy); d+=L(gx,gy+gh,gx+gw*0.9,cy); }
      else if(op.includes('Top')||op==='Bottom Hung'){ d+=L(gx,gy+gh,cx,gy+gh*0.1); d+=L(gx+gw,gy+gh,cx,gy+gh*0.1); }
      else if(op.includes('Tilt')){ d+=L(gx,gy+gh,cx,gy+gh*0.1); d+=L(gx+gw,gy+gh,cx,gy+gh*0.1); d+=L(gx+gw,gy,gx+gw*0.1,cy); }
      else if(op.includes('Slid')){ d+=L(gx+gw*0.15,cy,gx+gw*0.85,cy); }
      return d;
    }
    function handle(p, gx, gy, gw, gh){
      const op=p.opening||p.opener||'Fixed';
      if(!op||op==='Fixed'||op==='Fixed light'||op.includes('Slid')) return '';
      let hx,hy,vert=true;
      if(op.includes('Left')){ hx=gx+gw-bar*0.5; hy=gy+gh/2; }
      else if(op.includes('Right')){ hx=gx+bar*0.5; hy=gy+gh/2; }
      else if(op.includes('Top')||op.includes('Tilt')){ hx=gx+gw/2; hy=gy+gh-bar*0.5; vert=false; }
      else if(op==='Bottom Hung'){ hx=gx+gw/2; hy=gy+bar*0.5; vert=false; }
      else if(op==='French'||op==='Casement'){ hx=gx+gw-bar*0.5; hy=gy+gh/2; }
      else return '';
      const sc=Math.max(bar*0.5, Math.min(gw,gh)*0.05);
      const ht=model.frame.handleType||'lever';
      const R=(x,y,w,h,r)=>`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${r||0}" fill="${handleHex}" stroke="rgba(0,0,0,.35)" stroke-width="0.7"/>`;
      const C=(x,y,r,f)=>`<circle cx="${x}" cy="${y}" r="${r}" fill="${f||handleHex}" stroke="rgba(0,0,0,.35)" stroke-width="0.7"/>`;
      let o='';
      if(ht==='knob'){ o+=C(hx,hy,sc*0.9); o+=C(hx,hy,sc*0.5,'rgba(255,255,255,.18)'); return o; }
      if(ht==='tbar'){ const bl=Math.min(gh*0.5,sc*7); o+=R(hx-sc*0.22,hy-bl/2,sc*0.44,bl,sc*0.2); o+=C(hx,hy-bl/2+sc*0.4,sc*0.28); o+=C(hx,hy+bl/2-sc*0.4,sc*0.28); return o; }
      o+=R(hx-sc*0.35,hy-sc*0.8,sc*0.7,sc*1.6,sc*0.3); // rosette
      if(ht==='monkeytail'){
        o+= vert
          ? `<path d="M${hx-sc*0.18} ${hy} L${hx-sc*0.18} ${hy+sc*1.7} Q${hx-sc*0.18} ${hy+sc*2.3} ${hx+sc*0.5} ${hy+sc*2.2} Q${hx+sc*0.95} ${hy+sc*2.1} ${hx+sc*0.55} ${hy+sc*1.7} L${hx+sc*0.18} ${hy} Z" fill="${handleHex}" stroke="rgba(0,0,0,.35)" stroke-width="0.7"/>`
          : `<path d="M${hx} ${hy-sc*0.18} L${hx-sc*1.7} ${hy-sc*0.18} Q${hx-sc*2.3} ${hy-sc*0.18} ${hx-sc*2.2} ${hy+sc*0.5} Q${hx-sc*2.1} ${hy+sc*0.95} ${hx-sc*1.7} ${hy+sc*0.55} L${hx} ${hy+sc*0.18} Z" fill="${handleHex}" stroke="rgba(0,0,0,.35)" stroke-width="0.7"/>`;
      } else if(ht==='cockspur'){
        o+= vert ? R(hx-sc*0.25,hy-sc*0.1,sc*0.5,sc*1.1,sc*0.2) : R(hx-sc*1.1,hy-sc*0.25,sc*1.1,sc*0.5,sc*0.2);
        o+=C(hx,hy,sc*0.28);
      } else { // lever
        o+= vert ? R(hx-sc*0.22,hy-sc*0.15,sc*0.44,sc*2.1,sc*0.22) : R(hx-sc*2.1+sc*0.44,hy-sc*0.22,sc*2.1,sc*0.44,sc*0.22);
      }
      o+=C(hx,hy,sc*0.16,'rgba(0,0,0,.35)');
      return o;
    }
    function overlays(p, gx, gy, gw, gh){
      let o='';
      if(p.texture && p.texture!=='Clear')
        o+=`<rect x="${gx}" y="${gy}" width="${gw}" height="${gh}" fill="rgba(255,255,255,0.12)"/>`;
      if(p.leaded && p.leaded!=='none'){
        const step=Math.max(140,bar*2), cid='ld'+Math.random().toString(36).slice(2,7);
        let lines='';
        if(p.leaded==='diamond'){ for(let dd=-gh; dd<gw+gh; dd+=step){ lines+=`<line x1="${gx+dd}" y1="${gy}" x2="${gx+dd-gh}" y2="${gy+gh}" stroke="#7d8489" stroke-width="1.6"/><line x1="${gx+dd}" y1="${gy}" x2="${gx+dd+gh}" y2="${gy+gh}" stroke="#7d8489" stroke-width="1.6"/>`; } }
        else { for(let vx=gx+step; vx<gx+gw; vx+=step) lines+=`<line x1="${vx}" y1="${gy}" x2="${vx}" y2="${gy+gh}" stroke="#7d8489" stroke-width="1.6"/>`; for(let vy=gy+step; vy<gy+gh; vy+=step) lines+=`<line x1="${gx}" y1="${vy}" x2="${gx+gw}" y2="${vy}" stroke="#7d8489" stroke-width="1.6"/>`; }
        o+=`<defs><clipPath id="${cid}"><rect x="${gx}" y="${gy}" width="${gw}" height="${gh}"/></clipPath></defs><g clip-path="url(#${cid})">${lines}</g>`;
      }
      return o;
    }

    // panes glass + bars + appearance
    for (const p of model.panes) {
      const gx = ox + p.x*W + bar, gy = oy + p.y*H + bar;
      const gw = p.w*W - 2*bar, gh = p.h*H - 2*bar;
      if (gw<=0||gh<=0) continue;
      s += `<rect x="${gx}" y="${gy}" width="${gw}" height="${gh}" fill="${glassFill}" stroke="rgba(80,120,140,.5)" stroke-width="${Math.max(2,bar*0.1)}"/>`;
      s += overlays(p, gx, gy, gw, gh);
      for (const gb of (p.glazingBars||[])) {
        const t = gb.thickness||18;
        if (gb.type==='vertical') s += `<rect x="${gx+gw*gb.pos-t/2}" y="${gy}" width="${t}" height="${gh}" fill="${col}"/>`;
        else s += `<rect x="${gx}" y="${gy+gh*gb.pos-t/2}" width="${gw}" height="${t}" fill="${col}"/>`;
      }
      s += opener(p, gx, gy, gw, gh);
      s += handle(p, gx, gy, gw, gh);
    }
    // frame band (evenodd)
    s += `<path d="M ${ox} ${oy} H ${ox+W} V ${oy+H} H ${ox} Z M ${ox+bar} ${oy+bar} V ${oy+H-bar} H ${ox+W-bar} V ${oy+bar} Z" fill-rule="evenodd" fill="${col}" stroke="rgba(0,0,0,.35)" stroke-width="1"/>`;
    // projecting cill
    if (model.frame.cill) {
      const ch=30, lip=40, cy=oy+H;
      s += `<rect x="${ox-lip}" y="${cy}" width="${W+lip*2}" height="${ch}" fill="${col}" stroke="rgba(0,0,0,.35)" stroke-width="1"/>`;
      s += `<rect x="${ox-lip}" y="${cy+ch*0.7}" width="${W+lip*2}" height="${ch*0.3}" fill="rgba(0,0,0,.15)"/>`;
    }
    // mullions — draw only where panes share that edge (not full-width)
    const vEd = _collectEdgeSpans(model.panes, 'v', W, H);
    const hEd = _collectEdgeSpans(model.panes, 'h', W, H);
    for (const [rx, spans] of vEd) {
      for (const [y1, y2] of _mergeRanges(spans)) {
        s += `<rect x="${ox+rx*W-bar*0.3}" y="${oy+y1}" width="${bar*0.6}" height="${y2-y1}" fill="${col}"/>`;
      }
    }
    for (const [ty, spans] of hEd) {
      for (const [x1, x2] of _mergeRanges(spans)) {
        s += `<rect x="${ox+x1}" y="${oy+ty*H-bar*0.3}" width="${x2-x1}" height="${bar*0.6}" fill="${col}"/>`;
      }
    }
    // door extras
    if (model.unitType === 'door') {
      const d = model.door||{};
      if (d.slL>0) s += `<rect x="${ox+d.slL-bar*0.3}" y="${oy+bar}" width="${bar*0.6}" height="${H-2*bar}" fill="${col}"/>`;
      if (d.slR>0) s += `<rect x="${ox+W-d.slR-bar*0.3}" y="${oy+bar}" width="${bar*0.6}" height="${H-2*bar}" fill="${col}"/>`;
      if (d.flH>0) s += `<rect x="${ox+bar}" y="${oy+d.flH-bar*0.3}" width="${W-2*bar}" height="${bar*0.6}" fill="${col}"/>`;
      if (d.dtype==='double'||d.leafCount===2) s += `<rect x="${ox+W/2-bar*0.4}" y="${oy+bar}" width="${bar*0.8}" height="${H-2*bar}" fill="${col}"/>`;
    }
  } else {
    // shaped: clip glass to inner shape, then frame band
    const outerD = shapePath(0), innerD = shapePath(bar);
    s += `<defs><clipPath id="${clipId}"><path d="${innerD}"/></clipPath></defs>`;
    s += `<g clip-path="url(#${clipId})">`;
    s += `<rect x="${ox}" y="${oy}" width="${W}" height="${H}" fill="${glassFill}"/>`;
    for (const p of model.panes) {
      const gx = ox + p.x*W + bar, gy = oy + p.y*H + bar;
      const gw = p.w*W - 2*bar, gh = p.h*H - 2*bar;
      if (gw>0&&gh>0) s += `<rect x="${gx}" y="${gy}" width="${gw}" height="${gh}" fill="${glassFill}" stroke="rgba(80,120,140,.5)" stroke-width="${Math.max(2,bar*0.1)}"/>`;
    }
    s += `</g>`;
    s += `<path d="${outerD} ${innerD}" fill-rule="evenodd" fill="${col}" stroke="rgba(0,0,0,.35)" stroke-width="1"/>`;
  }

  s += `</svg>`;
  return s;
}

/* export to window */
window.QSDraw = { WindowModel, DrawingCanvas, TEMPLATES, templateToPanes, templateToModel, templatesByCategory, renderUnitSVG };