/* QS Finish Library
 * Realistic frame finishes (painted, textured, woodgrain foil, metallic) and
 * glass tints / patterns for the SVG editor. Exposes window.QSFinish.
 * Additive: it does not modify drawing-engine.js. Load it before the engine.
 */
(function (root) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  let _seq = 0;

  /* ------------------------------------------------------------------ */
  /*  Catalogue                                                          */
  /* ------------------------------------------------------------------ */
  const RAL = [
    { code: '9016', name: 'Pure White',      hex: '#F1F0EA' },
    { code: '9001', name: 'Cream',           hex: '#E9E0CC' },
    { code: '7038', name: 'Agate Grey',      hex: '#B4B8B0' },
    { code: '7035', name: 'Light Grey',      hex: '#C5C7C4' },
    { code: '7040', name: 'Window Grey',     hex: '#9DA3A6' },
    { code: '7012', name: 'Basalt Grey',     hex: '#575D5E' },
    { code: '7016', name: 'Anthracite Grey', hex: '#383E42' },
    { code: '9011', name: 'Graphite Black',  hex: '#292C2F' },
    { code: '9005', name: 'Jet Black',       hex: '#0E0E10' },
    { code: '8022', name: 'Black Brown',     hex: '#1A1718' },
    { code: '8017', name: 'Chocolate Brown', hex: '#45322E' },
    { code: '8014', name: 'Sepia Brown',     hex: '#4A3526' },
    { code: '6005', name: 'Moss Green',      hex: '#2F4538' },
    { code: '6009', name: 'Fir Green',       hex: '#27352A' },
    { code: '5011', name: 'Steel Blue',      hex: '#1A2B3C' },
    { code: '5014', name: 'Pigeon Blue',     hex: '#637D96' },
    { code: '3005', name: 'Burgundy',        hex: '#5E2129' },
    { code: '',     name: 'Midnight',        hex: '#1B2430' },
    { code: '',     name: 'Sage',            hex: '#4A6741' }
  ];

  /* along / across = grain feature frequency in cycles per mm */
  const WOODS = {
    golden_oak:  { name: 'Golden Oak',  base: '#B07A3B', dark: '#7E4F22', light: '#D29C57', along: 0.0035, across: 0.085, pore: 0.9, rings: 0.55, seed: 3 },
    natural_oak: { name: 'Natural Oak', base: '#C79A5E', dark: '#946A35', light: '#E2BC82', along: 0.0035, across: 0.085, pore: 0.8, rings: 0.50, seed: 5 },
    light_oak:   { name: 'Light Oak',   base: '#D8B787', dark: '#B08A55', light: '#EBD3AA', along: 0.0030, across: 0.080, pore: 0.7, rings: 0.45, seed: 8 },
    dark_oak:    { name: 'Dark Oak',    base: '#6B4423', dark: '#3F2512', light: '#8D6238', along: 0.0035, across: 0.085, pore: 0.9, rings: 0.60, seed: 13 },
    walnut:      { name: 'Walnut',      base: '#5A3A24', dark: '#321D10', light: '#7A5337', along: 0.0030, across: 0.070, pore: 0.8, rings: 0.65, seed: 21 },
    rosewood:    { name: 'Rosewood',    base: '#6E2F25', dark: '#3E160F', light: '#924638', along: 0.0030, across: 0.060, pore: 0.7, rings: 0.70, seed: 34 },
    mahogany:    { name: 'Mahogany',    base: '#5B2A1F', dark: '#331510', light: '#7C3D2C', along: 0.0030, across: 0.065, pore: 0.7, rings: 0.60, seed: 55 },
    teak:        { name: 'Teak',        base: '#A06A3A', dark: '#6F4520', light: '#C38E58', along: 0.0035, across: 0.075, pore: 0.8, rings: 0.55, seed: 89 },
    cherry:      { name: 'Cherry',      base: '#8A4A32', dark: '#5C2D1B', light: '#AE6A4A', along: 0.0030, across: 0.070, pore: 0.6, rings: 0.50, seed: 144 },
    black_ash:   { name: 'Black Ash',   base: '#2A2522', dark: '#120F0D', light: '#443C37', along: 0.0035, across: 0.090, pore: 0.9, rings: 0.45, seed: 233 },
    grey_oak:    { name: 'Grey Oak',    base: '#8A8379', dark: '#5C564E', light: '#B0A89B', along: 0.0035, across: 0.085, pore: 0.8, rings: 0.50, seed: 377 }
  };

  /* gloss 0..1 */
  const FINISHES = {
    painted_smooth: { name: 'Smooth painted',      kind: 'paint',    gloss: 0.35 },
    painted_satin:  { name: 'Satin painted',       kind: 'paint',    gloss: 0.18 },
    painted_matt:   { name: 'Matt painted',        kind: 'paint',    gloss: 0.05 },
    textured:       { name: 'Textured RAL',        kind: 'textured', gloss: 0.04 },
    wood:           { name: 'Woodgrain foil',      kind: 'wood',     gloss: 0.10 },
    metallic:       { name: 'Metallic / anodised', kind: 'metallic', gloss: 0.60 }
  };

  const GLASS_TINTS = {
    clear:      { name: 'Clear',              top: '#D4EAF2', bot: '#A5C6D2', alpha: 0.30 },
    grey:       { name: 'Grey',               top: '#9AA3A8', bot: '#5F686D', alpha: 0.45 },
    bronze:     { name: 'Bronze',             top: '#C9AA86', bot: '#8A6A46', alpha: 0.45 },
    bluegreen:  { name: 'Blue-green',         top: '#A9D4CF', bot: '#5F9E9A', alpha: 0.42 },
    reflective: { name: 'Neutral reflective', top: '#C3CED6', bot: '#7E8D98', alpha: 0.55 }
  };

  const GLASS_PATTERNS = {
    clear:           'Clear',
    satin:           'Satin',
    stippolyte:      'Stippolyte',
    cotswold:        'Cotswold',
    charcoal_sticks: 'Charcoal Sticks',
    reeded:          'Reeded',
    frosted:         'Frosted',
    pyramid:         'Pyramid',
    georgian_wired:  'Georgian wired'
  };

  /* ------------------------------------------------------------------ */
  /*  Helpers                                                            */
  /* ------------------------------------------------------------------ */
  function el(name, attrs, parent) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }

  function nextId(prefix) { return prefix + '_' + (++_seq); }

  function hexToRgb(hex) {
    const h = String(hex || '#000000').replace('#', '');
    return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0];
  }

  function mix(a, b, t) {
    const A = hexToRgb(a), B = hexToRgb(b);
    return A.map((v, i) => Math.round(v + (B[i] - v) * t));
  }

  function rgbToHex(rgb) {
    return '#' + rgb.map(v => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('');
  }

  function norm(v) { return String(v || '').trim().toLowerCase().replace(/[\s\-]+/g, '_'); }

  function clampF(f) { return Math.min(0.45, Math.max(0.0005, f)); }

  function fmt(n) { return Number(n).toFixed(4); }

  /* Per-render defs: drawing-engine clears the svg on every render, so the
     defs group is recreated automatically when it is no longer attached. */
  function state(svg) {
    const rootSvg = svg.ownerSVGElement || svg;
    let s = rootSvg.__qsf;
    if (!s || s.defs.parentNode !== rootSvg) {
      const defs = el('defs', {}, rootSvg);
      s = rootSvg.__qsf = { defs: defs, cache: {} };
    }
    return s;
  }

  function resolve(frame) {
    frame = frame || {};
    const key = norm(frame.finish);
    const def = FINISHES[key];
    if (!def) return { active: false };
    const wood = WOODS[norm(frame.wood)] || WOODS.natural_oak;
    return {
      active: true,
      key: key,
      kind: def.kind,
      gloss: def.gloss,
      woodKey: WOODS[norm(frame.wood)] ? norm(frame.wood) : 'natural_oak',
      wood: wood,
      color: def.kind === 'wood' ? wood.base : (frame.color || '#2B2F33')
    };
  }

  function baseColor(frame) {
    const r = resolve(frame);
    return r.active ? r.color : (frame && frame.color) || '#2B2F33';
  }

  /* ------------------------------------------------------------------ */
  /*  Wood grain filter (grain runs along the bar length)                */
  /* ------------------------------------------------------------------ */
  function woodFilter(svg, key, dir, pxPerMm) {
    const s = state(svg);
    const ck = ['w', key, dir, Math.round(pxPerMm * 100)].join('|');
    if (s.cache[ck]) return s.cache[ck];

    const w = WOODS[key] || WOODS.natural_oak;
    const id = nextId('qsfW');
    const scale = Math.max(pxPerMm, 0.02);

    const fa = w.along / scale;     // along the grain (long features)
    const fc = w.across / scale;    // across the grain (fine lines)
    const bf = (a, c) => (dir === 'v' ? fmt(clampF(c)) + ' ' + fmt(clampF(a)) : fmt(clampF(a)) + ' ' + fmt(clampF(c)));

    const f = el('filter', {
      id: id, x: '0', y: '0', width: '100%', height: '100%',
      'color-interpolation-filters': 'sRGB'
    }, s.defs);

    // 1. main grain lines, stretched along the bar
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: bf(fa, fc), numOctaves: '3', seed: String(w.seed), result: 'n1' }, f);
    el('feColorMatrix', { in: 'n1', type: 'matrix', values: '1 0 0 0 0  1 0 0 0 0  1 0 0 0 0  0 0 0 0 1', result: 'g1' }, f);

    const stretch = el('feComponentTransfer', { in: 'g1', result: 'g1c' }, f);
    ['feFuncR', 'feFuncG', 'feFuncB'].forEach(n => el(n, { type: 'linear', slope: '2.4', intercept: '-0.7' }, stretch));

    const stops = [
      rgbToHex(hexToRgb(w.dark)),
      rgbToHex(mix(w.dark, w.base, 0.55)),
      rgbToHex(hexToRgb(w.base)),
      rgbToHex(hexToRgb(w.light))
    ].map(hexToRgb);

    const tint = el('feComponentTransfer', { in: 'g1c', result: 'tint' }, f);
    [['feFuncR', 0], ['feFuncG', 1], ['feFuncB', 2]].forEach(p => {
      el(p[0], { type: 'table', tableValues: stops.map(c => (c[p[1]] / 255).toFixed(3)).join(' ') }, tint);
    });

    // 2. fine pores
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: bf(fa * 3, fc * 4), numOctaves: '2', seed: String(w.seed + 7), result: 'n2' }, f);
    const poreA = (1.6 * w.pore).toFixed(3), poreB = (0.8 * w.pore).toFixed(3);
    el('feColorMatrix', { in: 'n2', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -' + poreA + ' 0 0 0 ' + poreB, result: 'pores' }, f);

    // 3. broad ring / cathedral variation
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: bf(fa * 0.35, fc * 0.22), numOctaves: '2', seed: String(w.seed + 19), result: 'n3' }, f);
    const ringA = (1.4 * w.rings).toFixed(3), ringB = (0.7 * w.rings).toFixed(3);
    el('feColorMatrix', { in: 'n3', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -' + ringA + ' 0 0 0 ' + ringB, result: 'rings' }, f);

    const merge = el('feMerge', { result: 'wood' }, f);
    ['tint', 'pores', 'rings'].forEach(n => el('feMergeNode', { in: n }, merge));

    el('feComposite', { in: 'wood', in2: 'SourceAlpha', operator: 'in' }, f);

    s.cache[ck] = id;
    return id;
  }

  /* ------------------------------------------------------------------ */
  /*  Textured (sand) finish filter                                      */
  /* ------------------------------------------------------------------ */
  function texturedFilter(svg) {
    const s = state(svg);
    if (s.cache.tex) return s.cache.tex;
    const id = nextId('qsfT');
    const f = el('filter', { id: id, x: '0', y: '0', width: '100%', height: '100%', 'color-interpolation-filters': 'sRGB' }, s.defs);
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: '0.75', numOctaves: '2', seed: '5', result: 'n' }, f);
    el('feColorMatrix', { in: 'n', type: 'matrix', values: '0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1.5 0 0 0 -0.6', result: 'dark' }, f);
    el('feColorMatrix', { in: 'n', type: 'matrix', values: '0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  -1.3 0 0 0 0.55', result: 'light' }, f);
    const merge = el('feMerge', { result: 'all' }, f);
    ['SourceGraphic', 'dark', 'light'].forEach(n => el('feMergeNode', { in: n }, merge));
    el('feComposite', { in: 'all', in2: 'SourceAlpha', operator: 'in' }, f);
    s.cache.tex = id;
    return id;
  }

  /* ------------------------------------------------------------------ */
  /*  Paint sheen / metallic gradients                                   */
  /* ------------------------------------------------------------------ */
  function sheenGradient(svg, dir, gloss, metallic) {
    const s = state(svg);
    const ck = ['s', dir, gloss, metallic ? 1 : 0].join('|');
    if (s.cache[ck]) return s.cache[ck];

    const id = nextId('qsfS');
    const g = el('linearGradient', {
      id: id,
      x1: '0', y1: '0',
      x2: dir === 'v' ? '1' : '0',
      y2: dir === 'v' ? '0' : '1'
    }, s.defs);

    const spec = Math.min(0.8, gloss * 1.1);
    const shade = 0.12 + 0.10 * gloss;
    const add = (o, c, a) => el('stop', { offset: o, 'stop-color': c, 'stop-opacity': a.toFixed(3) }, g);

    if (metallic) {
      add('0', '#FFFFFF', 0.45);
      add('0.20', '#FFFFFF', 0.10);
      add('0.38', '#000000', 0.18);
      add('0.55', '#FFFFFF', 0.50);
      add('0.78', '#000000', 0.12);
      add('1', '#000000', 0.34);
    } else {
      add('0', '#FFFFFF', spec * 0.55);
      add('0.28', '#FFFFFF', spec);
      add('0.44', '#FFFFFF', spec * 0.10);
      add('0.75', '#000000', shade * 0.30);
      add('1', '#000000', shade);
    }
    s.cache[ck] = id;
    return id;
  }

  /* ------------------------------------------------------------------ */
  /*  Frame decoration                                                   */
  /* ------------------------------------------------------------------ */
  function applyFinish(shapeEl, spec, svg, dir, pxPerMm) {
    // returns the list of elements that should be stacked, in order
    const out = [];
    if (spec.kind === 'wood') {
      shapeEl.setAttribute('fill', '#000');
      shapeEl.setAttribute('filter', 'url(#' + woodFilter(svg, spec.woodKey, dir, pxPerMm) + ')');
    } else if (spec.kind === 'textured') {
      shapeEl.setAttribute('fill', spec.color);
      shapeEl.setAttribute('filter', 'url(#' + texturedFilter(svg) + ')');
    } else {
      shapeEl.setAttribute('fill', spec.color);
    }
    shapeEl.setAttribute('pointer-events', 'none');
    out.push(shapeEl);
    return out;
  }

  /* Rectangular bar. dir: 'h' (top/bottom bars) or 'v' (left/right bars). */
  function decorateBar(svg, x, y, w, h, dir, frame, pxPerMm, parent) {
    const spec = resolve(frame);
    if (!spec.active) return false;
    parent = parent || svg;

    const grain = el('rect', { x: x, y: y, width: w, height: h });
    applyFinish(grain, spec, svg, dir, pxPerMm).forEach(e => parent.appendChild(e));

    const sheen = el('rect', {
      x: x, y: y, width: w, height: h,
      fill: 'url(#' + sheenGradient(svg, dir, spec.gloss, spec.kind === 'metallic') + ')',
      'pointer-events': 'none'
    });
    parent.appendChild(sheen);
    return true;
  }

  /* Curved / shaped frame band (outer + inner path, even-odd). */
  function decoratePath(svg, d, frame, pxPerMm, dir, parent) {
    const spec = resolve(frame);
    if (!spec.active) return false;
    parent = parent || svg;

    const grain = el('path', { d: d, 'fill-rule': 'evenodd' });
    applyFinish(grain, spec, svg, dir || 'h', pxPerMm).forEach(e => parent.appendChild(e));

    parent.appendChild(el('path', {
      d: d, 'fill-rule': 'evenodd',
      fill: 'url(#' + sheenGradient(svg, dir || 'h', spec.gloss, spec.kind === 'metallic') + ')',
      'pointer-events': 'none'
    }));
    return true;
  }

  /* ------------------------------------------------------------------ */
  /*  Glass                                                              */
  /* ------------------------------------------------------------------ */
  function noiseFilter(svg, p) {
    const s = state(svg);
    const ck = 'n|' + [p.freq, p.oct, p.seed, p.a, p.b].join('|');
    if (s.cache[ck]) return s.cache[ck];
    const id = nextId('qsfN');
    const f = el('filter', { id: id, x: '0', y: '0', width: '100%', height: '100%', 'color-interpolation-filters': 'sRGB' }, s.defs);
    el('feTurbulence', { type: 'fractalNoise', baseFrequency: p.freq, numOctaves: String(p.oct), seed: String(p.seed), result: 'n' }, f);
    el('feColorMatrix', { in: 'n', type: 'matrix', values: '0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  ' + p.a + ' 0 0 0 ' + p.b, result: 'w' }, f);
    el('feComposite', { in: 'w', in2: 'SourceAlpha', operator: 'in' }, f);
    s.cache[ck] = id;
    return id;
  }

  function tintGradient(svg, key) {
    const s = state(svg);
    const ck = 't|' + key;
    if (s.cache[ck]) return s.cache[ck];
    const t = GLASS_TINTS[key] || GLASS_TINTS.clear;
    const id = nextId('qsfG');
    const g = el('linearGradient', { id: id, x1: '0', y1: '0', x2: '0.35', y2: '1' }, s.defs);
    el('stop', { offset: '0', 'stop-color': t.top, 'stop-opacity': t.alpha.toFixed(2) }, g);
    el('stop', { offset: '1', 'stop-color': t.bot, 'stop-opacity': Math.min(0.85, t.alpha + 0.12).toFixed(2) }, g);
    s.cache[ck] = id;
    return id;
  }

  function glassPattern(svg, key, pxPerMm) {
    const s = state(svg);
    const ck = 'p|' + key + '|' + Math.round(pxPerMm * 100);
    if (s.cache[ck]) return s.cache[ck];
    const id = nextId('qsfP');
    const sc = Math.max(pxPerMm, 0.02);

    if (key === 'reeded') {
      const pw = Math.max(4, 12 * sc);
      const grad = el('linearGradient', { id: id + 'g', x1: '0', y1: '0', x2: '1', y2: '0' }, s.defs);
      el('stop', { offset: '0', 'stop-color': '#FFFFFF', 'stop-opacity': '0.38' }, grad);
      el('stop', { offset: '0.5', 'stop-color': '#000000', 'stop-opacity': '0.10' }, grad);
      el('stop', { offset: '1', 'stop-color': '#FFFFFF', 'stop-opacity': '0.38' }, grad);
      const p = el('pattern', { id: id, width: pw, height: 20, patternUnits: 'userSpaceOnUse' }, s.defs);
      el('rect', { x: 0, y: 0, width: pw, height: 20, fill: 'url(#' + id + 'g)' }, p);
    } else if (key === 'charcoal_sticks') {
      const pw = Math.max(14, 26 * sc), ph = Math.max(40, 90 * sc);
      const p = el('pattern', { id: id, width: pw, height: ph, patternUnits: 'userSpaceOnUse' }, s.defs);
      const bar = (fx, fy, fh) => el('rect', { x: pw * fx, y: ph * fy, width: 1.4, height: ph * fh, fill: '#1F2428', opacity: '0.75' }, p);
      bar(0.20, 0.05, 0.55); bar(0.55, 0.50, 0.35); bar(0.80, 0.10, 0.50);
    } else if (key === 'pyramid') {
      const sz = Math.max(8, 14 * sc);
      const p = el('pattern', { id: id, width: sz, height: sz, patternUnits: 'userSpaceOnUse' }, s.defs);
      el('path', { d: 'M0 ' + sz / 2 + ' L ' + sz / 2 + ' 0 L ' + sz + ' ' + sz / 2 + ' L ' + sz / 2 + ' ' + sz + ' Z', fill: 'none', stroke: '#FFFFFF', 'stroke-opacity': '0.55', 'stroke-width': '1' }, p);
      el('path', { d: 'M0 0 L ' + sz + ' ' + sz + ' M ' + sz + ' 0 L 0 ' + sz, fill: 'none', stroke: '#000000', 'stroke-opacity': '0.10', 'stroke-width': '1' }, p);
    } else if (key === 'georgian_wired') {
      const sz = Math.max(10, 25 * sc);
      const p = el('pattern', { id: id, width: sz, height: sz, patternUnits: 'userSpaceOnUse' }, s.defs);
      el('path', { d: 'M0 0 H ' + sz + ' M0 0 V ' + sz, fill: 'none', stroke: '#59636A', 'stroke-opacity': '0.85', 'stroke-width': '1' }, p);
      el('path', { d: 'M0 0 L ' + sz + ' ' + sz, fill: 'none', stroke: '#59636A', 'stroke-opacity': '0.25', 'stroke-width': '0.6' }, p);
    } else {
      return null;
    }
    s.cache[ck] = id;
    return id;
  }

  /* Draws tint + pattern over one pane's glass area. pane.tint / pane.texture */
  function decorateGlass(svg, x, y, w, h, pane, pxPerMm, parent) {
    pane = pane || {};
    parent = parent || svg;
    const tintKey = GLASS_TINTS[norm(pane.tint)] ? norm(pane.tint) : 'clear';
    const patKey = norm(pane.texture) || 'clear';

    const add = (attrs) => {
      attrs.x = x; attrs.y = y; attrs.width = w; attrs.height = h;
      attrs['pointer-events'] = 'none';
      parent.appendChild(el('rect', attrs));
    };

    if (tintKey !== 'clear') {
      add({ fill: 'url(#' + tintGradient(svg, tintKey) + ')' });
    }

    const noise = (freq, oct, seed, a, b, opacity) =>
      add({ fill: '#FFFFFF', opacity: String(opacity), filter: 'url(#' + noiseFilter(svg, { freq: freq, oct: oct, seed: seed, a: a, b: b }) + ')' });

    switch (patKey) {
      case 'satin':
        noise('0.55', 2, 4, '0.5', '0.25', 0.50);
        break;
      case 'frosted':
        noise('0.90', 2, 11, '0.9', '0.10', 0.62);
        break;
      case 'stippolyte':
        noise('0.55', 2, 4, '0.5', '0.25', 0.40);
        noise('0.16', 1, 9, '-9', '4.3', 0.55);
        break;
      case 'cotswold':
        noise('0.55', 2, 4, '0.5', '0.25', 0.30);
        noise('0.020 0.050', 2, 6, '-3.2', '1.9', 0.35);
        break;
      case 'charcoal_sticks':
        noise('0.55', 2, 4, '0.5', '0.25', 0.30);
        add({ fill: 'url(#' + glassPattern(svg, 'charcoal_sticks', pxPerMm) + ')' });
        break;
      case 'reeded':
      case 'pyramid':
      case 'georgian_wired': {
        const pid = glassPattern(svg, patKey, pxPerMm);
        if (pid) add({ fill: 'url(#' + pid + ')' });
        break;
      }
      default:
        break;
    }
    return true;
  }

  /* ------------------------------------------------------------------ */
  /*  Public API                                                         */
  /* ------------------------------------------------------------------ */
  root.QSFinish = {
    RAL: RAL,
    WOODS: WOODS,
    FINISHES: FINISHES,
    GLASS_TINTS: GLASS_TINTS,
    GLASS_PATTERNS: GLASS_PATTERNS,
    resolve: resolve,
    baseColor: baseColor,
    isActive: function (frame) { return resolve(frame).active; },
    decorateBar: decorateBar,
    decoratePath: decoratePath,
    decorateGlass: decorateGlass
  };
})(window);
