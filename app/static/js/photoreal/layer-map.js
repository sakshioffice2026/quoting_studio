/* app/static/js/photoreal/layer-map.js
 *
 * Procedural window layer builder.
 * Turns a design JSON (same format as rasterDesign in visualiser.html) into
 * three small canvases that the WebGL shader consumes:
 *
 *   layerCanvas  RGB  R = outer frame, G = sash / mullion, B = muntin (glazing bar)
 *   heightCanvas gray bevelled height field (frame > muntin > sash > bead > glass)
 *   maskCanvas   RGB  R = glass, G = solid panel infill, B = inside outer shape
 *
 * Usage:
 *   const L = PhotorealLayers.build(design);
 *   L.layerCanvas / L.heightCanvas / L.maskCanvas / L.metrics / L.colors
 */
(function (root) {
  'use strict';

  var HEIGHT = {
    frame: 0.80, groove: 0.50, sash: 0.66, bead: 0.58,
    muntin: 0.74, glass: 0.26, panel: 0.70, panelEdge: 0.54
  };

  var _cache = new Map();
  var CACHE_MAX = 24;

  function gray(v) {
    var n = Math.round(Math.max(0, Math.min(1, v)) * 255);
    return 'rgb(' + n + ',' + n + ',' + n + ')';
  }

  function hexToRgb(hex, fallback) {
    if (typeof hex === 'string' && /^#[0-9a-fA-F]{6}$/.test(hex)) {
      return [
        parseInt(hex.slice(1, 3), 16) / 255,
        parseInt(hex.slice(3, 5), 16) / 255,
        parseInt(hex.slice(5, 7), 16) / 255
      ];
    }
    return fallback;
  }

  function makeCanvas(w, h) {
    var c = document.createElement('canvas');
    c.width = w; c.height = h;
    return c;
  }

  /* ---------- outline path (matches rasterDesign) ---------- */
  function makeOutline(ctx) {
    var W = ctx.W, H = ctx.H, s = ctx.s, shape = ctx.shape, rise = ctx.rise, isDoor = ctx.isDoor;
    return function (inset) {
      var x0 = inset * s, x1 = (W - inset) * s, y0 = inset * s;
      var y1 = (H - (isDoor ? 0 : inset)) * s;
      var w = x1 - x0, cx = x0 + w / 2, spring = y0 + rise * s;
      var p = new Path2D();
      if (shape === 'circular') {
        p.ellipse(cx, (y0 + y1) / 2, Math.max(w / 2, 0.01), Math.max((y1 - y0) / 2, 0.01), 0, 0, Math.PI * 2);
        return p;
      }
      if (shape === 'arched') {
        p.moveTo(x0, y1); p.lineTo(x0, spring);
        p.ellipse(cx, spring, Math.max(w / 2, 0.01), Math.max(spring - y0, 0.01), 0, Math.PI, Math.PI * 2, false);
        p.lineTo(x1, y1); p.closePath();
        return p;
      }
      if (shape === 'gothic') {
        var ctrl = y0 * 0.6 + spring * 0.4;
        p.moveTo(x0, y1); p.lineTo(x0, spring);
        p.quadraticCurveTo(x0, ctrl, cx, y0);
        p.quadraticCurveTo(x1, ctrl, x1, spring);
        p.lineTo(x1, y1); p.closePath();
        return p;
      }
      p.rect(x0, y0, w, y1 - y0);
      return p;
    };
  }

  /* ---------- pane rectangles (matches rasterDesign) ---------- */
  function paneRects(design, ctx) {
    var panes = (design.panes && design.panes.length) ? design.panes
      : [{ x: 0, y: 0, w: 1, h: 1, infill: 'glass', glazingBars: [] }];
    var W = ctx.W, H = ctx.H, s = ctx.s, bar = ctx.bar, isDoor = ctx.isDoor;
    var half = bar * 0.6 / 2, eps = 0.001;
    var out = [];
    panes.forEach(function (p) {
      var insL = (p.x <= eps) ? bar : half;
      var insT = (p.y <= eps) ? bar : half;
      var insR = (p.x + p.w >= 1 - eps) ? bar : half;
      var insB = (p.y + p.h >= 1 - eps) ? (isDoor ? 0 : bar) : half;
      var x = (p.x * W + insL) * s, y = (p.y * H + insT) * s;
      var w = (p.w * W - insL - insR) * s, h = (p.h * H - insT - insB) * s;
      if (w <= 0 || h <= 0) return;
      out.push({ x: x, y: y, w: w, h: h, panel: p.infill === 'panel', pane: p });
    });
    return out;
  }

  /* ---------- blur (ctx.filter where supported, box blur fallback) ---------- */
  function boxBlurRGBA(canvas, r) {
    var w = canvas.width, h = canvas.height;
    var g = canvas.getContext('2d');
    var img = g.getImageData(0, 0, w, h);
    var d = img.data, tmp = new Float32Array(w * h * 3);
    var rad = Math.max(1, Math.round(r));
    var win = rad * 2 + 1;
    var c, x, y, acc, i;
    for (var pass = 0; pass < 2; pass++) {
      for (y = 0; y < h; y++) {
        for (c = 0; c < 3; c++) {
          acc = 0;
          for (x = -rad; x <= rad; x++) acc += d[(y * w + Math.min(w - 1, Math.max(0, x))) * 4 + c];
          for (x = 0; x < w; x++) {
            tmp[(y * w + x) * 3 + c] = acc / win;
            var xa = Math.min(w - 1, x + rad + 1), xb = Math.max(0, x - rad);
            acc += d[(y * w + xa) * 4 + c] - d[(y * w + xb) * 4 + c];
          }
        }
      }
      for (x = 0; x < w; x++) {
        for (c = 0; c < 3; c++) {
          acc = 0;
          for (y = -rad; y <= rad; y++) acc += tmp[(Math.min(h - 1, Math.max(0, y)) * w + x) * 3 + c];
          for (y = 0; y < h; y++) {
            d[(y * w + x) * 4 + c] = acc / win;
            var ya = Math.min(h - 1, y + rad + 1), yb = Math.max(0, y - rad);
            acc += tmp[(ya * w + x) * 3 + c] - tmp[(yb * w + x) * 3 + c];
          }
        }
      }
    }
    for (i = 3; i < d.length; i += 4) d[i] = 255;
    g.putImageData(img, 0, 0);
    return canvas;
  }

  function blurCanvas(src, r) {
    if (r < 0.4) return src;
    var out = makeCanvas(src.width, src.height);
    var g = out.getContext('2d');
    if ('filter' in g) {
      g.filter = 'blur(' + r.toFixed(2) + 'px)';
      g.drawImage(src, 0, 0);
      g.filter = 'none';
      return out;
    }
    g.drawImage(src, 0, 0);
    return boxBlurRGBA(out, r);
  }

  /* ---------- finishes (additive: result.finish / result.finishCanvas) ---------- */
  var FINISHES = {
    painted_smooth: { kind: 'paint', gloss: 0.35, metallic: 0.0 },
    painted_satin: { kind: 'paint', gloss: 0.18, metallic: 0.0 },
    painted_matt: { kind: 'paint', gloss: 0.05, metallic: 0.0 },
    textured: { kind: 'textured', gloss: 0.04, metallic: 0.0 },
    wood: { kind: 'wood', gloss: 0.10, metallic: 0.0 },
    metallic: { kind: 'metallic', gloss: 0.60, metallic: 0.85 }
  };
  var WOODS = {
    golden_oak: { base: '#B07A3B', dark: '#7E4F22', light: '#D29C57', seed: 3, pore: 0.9 },
    natural_oak: { base: '#C79A5E', dark: '#946A35', light: '#E2BC82', seed: 5, pore: 0.8 },
    light_oak: { base: '#D8B787', dark: '#B08A55', light: '#EBD3AA', seed: 8, pore: 0.7 },
    dark_oak: { base: '#6B4423', dark: '#3F2512', light: '#8D6238', seed: 13, pore: 0.9 },
    walnut: { base: '#5A3A24', dark: '#321D10', light: '#7A5337', seed: 21, pore: 0.8 },
    rosewood: { base: '#6E2F25', dark: '#3E160F', light: '#924638', seed: 34, pore: 0.7 },
    mahogany: { base: '#5B2A1F', dark: '#331510', light: '#7C3D2C', seed: 55, pore: 0.7 },
    teak: { base: '#A06A3A', dark: '#6F4520', light: '#C38E58', seed: 89, pore: 0.8 },
    cherry: { base: '#8A4A32', dark: '#5C2D1B', light: '#AE6A4A', seed: 144, pore: 0.6 },
    black_ash: { base: '#2A2522', dark: '#120F0D', light: '#443C37', seed: 233, pore: 0.9 },
    grey_oak: { base: '#8A8379', dark: '#5C564E', light: '#B0A89B', seed: 377, pore: 0.8 }
  };

  function finishSpec(frame) {
    var key = String((frame && frame.finish) || '').trim().toLowerCase();
    var def = FINISHES[key];
    if (!def) return null;
    var wk = String((frame && frame.wood) || 'natural_oak').trim().toLowerCase();
    if (!WOODS[wk]) wk = 'natural_oak';
    return { key: key, kind: def.kind, gloss: def.gloss, metallic: def.metallic, woodKey: wk, wood: WOODS[wk] };
  }

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hexRgb255(hex) {
    var h = String(hex || '#000000').replace('#', '');
    return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0];
  }
  function mixRgb(a, b, t) {
    return [Math.round(a[0] + (b[0] - a[0]) * t), Math.round(a[1] + (b[1] - a[1]) * t), Math.round(a[2] + (b[2] - a[2]) * t)];
  }

  function grainCanvas(cw, ch, wood, vertical) {
    var cv = makeCanvas(cw, ch);
    var g = cv.getContext('2d');
    var rand = rng(wood.seed * 7919 + (vertical ? 1 : 0));
    var dark = hexRgb255(wood.dark), base = hexRgb255(wood.base), light = hexRgb255(wood.light);
    var across = vertical ? cw : ch, along = vertical ? ch : cw;
    g.fillStyle = wood.base; g.fillRect(0, 0, cw, ch);

    var p1 = rand() * 6.28, p2 = rand() * 6.28, p3 = rand() * 6.28;
    var i, v, rgb;
    for (i = 0; i < across; i++) {
      v = 0.5 + 0.22 * Math.sin(i * 0.11 + p1) + 0.14 * Math.sin(i * 0.37 + p2) +
          0.10 * Math.sin(i * 0.013 + p3) + (rand() - 0.5) * 0.30;
      v = Math.max(0, Math.min(1, v));
      rgb = v < 0.5 ? mixRgb(dark, base, v * 2) : mixRgb(base, light, (v - 0.5) * 2);
      g.fillStyle = 'rgb(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ')';
      if (vertical) g.fillRect(i, 0, 1, along); else g.fillRect(0, i, along, 1);
    }

    var streaks = Math.round(across * 0.9), s, pos, len, start;
    for (s = 0; s < streaks; s++) {
      pos = rand() * across; len = 30 + rand() * 260; start = rand() * along - len * 0.3;
      g.fillStyle = rand() < 0.55 ? 'rgba(0,0,0,' + (0.04 + rand() * 0.07).toFixed(3) + ')'
        : 'rgba(255,255,255,' + (0.03 + rand() * 0.06).toFixed(3) + ')';
      if (vertical) g.fillRect(pos, start, 1 + rand() * 1.5, len); else g.fillRect(start, pos, len, 1 + rand() * 1.5);
    }

    var pores = Math.round(across * along * 0.0035 * wood.pore);
    g.fillStyle = 'rgba(0,0,0,0.20)';
    for (s = 0; s < pores; s++) {
      pos = rand() * across; start = rand() * along; len = 2 + rand() * 7;
      if (vertical) g.fillRect(pos, start, 1, len); else g.fillRect(start, pos, len, 1);
    }

    var knots = Math.min(3, Math.floor(along / 500)), k, kr, kg, cx, cy;
    for (k = 0; k < knots; k++) {
      if (rand() > 0.6) continue;
      var ky = across * (0.3 + rand() * 0.4), kx = along * (0.1 + rand() * 0.8);
      kr = Math.max(3, across * (0.10 + rand() * 0.06));
      cx = vertical ? ky : kx; cy = vertical ? kx : ky;
      kg = g.createRadialGradient(cx, cy, 0, cx, cy, kr * 1.6);
      kg.addColorStop(0, 'rgba(' + dark[0] + ',' + dark[1] + ',' + dark[2] + ',0.85)');
      kg.addColorStop(0.5, 'rgba(' + dark[0] + ',' + dark[1] + ',' + dark[2] + ',0.45)');
      kg.addColorStop(1, 'rgba(' + dark[0] + ',' + dark[1] + ',' + dark[2] + ',0)');
      g.save();
      g.translate(cx, cy);
      if (!vertical) g.scale(1.7, 1); else g.scale(1, 1.7);
      g.translate(-cx, -cy);
      g.fillStyle = kg;
      g.beginPath(); g.arc(cx, cy, kr * 1.6, 0, Math.PI * 2); g.fill();
      g.restore();
    }
    return cv;
  }

  /* albedo map for wood / textured frames; colour where layerCanvas marks frame or sash */
  function buildFinishCanvas(fin, frame, cw, ch, s, o) {
    if (fin.kind === 'wood') {
      var out = makeCanvas(cw, ch);
      var g = out.getContext('2d');
      g.drawImage(grainCanvas(cw, ch, fin.wood, false), 0, 0);
      var tV = grainCanvas(cw, ch, fin.wood, true);

      /* outer frame, straight jambs: vertical grain */
      var top = 0;
      if (o.shape === 'arched' || o.shape === 'gothic') top = (o.bar + o.rise) * s;
      if (o.shape !== 'circular') {
        g.save();
        g.beginPath();
        g.rect(0, top, o.barPx, ch - top);
        g.rect(cw - o.barPx, top, o.barPx, ch - top);
        g.clip();
        g.drawImage(tV, 0, 0);
        g.restore();
      }

      /* sash bars and muntins */
      g.save();
      g.clip(o.inner);
      var half = o.sashPx / 2;
      o.rects.forEach(function (r) {
        if (r.panel) return;
        g.save();
        g.beginPath();
        g.rect(r.x - half, r.y - half, half, r.h + o.sashPx);
        g.rect(r.x + r.w, r.y - half, half, r.h + o.sashPx);
        g.clip();
        g.drawImage(tV, 0, 0);
        g.restore();
        (r.pane.glazingBars || []).forEach(function (gb) {
          if (gb.type !== 'vertical') return;
          var t = Math.max(2, (gb.thickness || 18) * s);
          g.save();
          g.beginPath(); g.rect(r.x + r.w * gb.pos - t / 2, r.y, t, r.h); g.clip();
          g.drawImage(tV, 0, 0);
          g.restore();
        });
      });
      g.restore();
      return out;
    }

    if (fin.kind === 'textured') {
      var tc = makeCanvas(cw, ch);
      var tg = tc.getContext('2d');
      tg.fillStyle = frame.color || '#2B2F33';
      tg.fillRect(0, 0, cw, ch);
      var r2 = rng(77), n = Math.round(cw * ch * 0.06), i;
      for (i = 0; i < n; i++) {
        tg.fillStyle = r2() < 0.55 ? 'rgba(0,0,0,0.34)' : 'rgba(255,255,255,0.26)';
        tg.fillRect(r2() * cw, r2() * ch, 1, 1);
      }
      return tc;
    }
    return null;
  }

  /* ---------- main build ---------- */
  function build(design, opts) {
    design = design || {};
    opts = opts || {};
    var key = JSON.stringify([design, opts.maxSize || 1400]);
    if (_cache.has(key)) return _cache.get(key);

    var W = design.width || 1200, H = design.height || 1400;
    var s = (opts.maxSize || 1400) / Math.max(W, H);
    var cw = Math.max(60, Math.round(W * s)), ch = Math.max(60, Math.round(H * s));

    var frame = design.frame || {};
    var bar = frame.thickness || 68;
    var shape = design.shape || 'rectangle';
    var isDoor = design.unitType === 'door';
    var rise = (design.archRise != null) ? design.archRise : Math.min(W * 0.25, 400);
    var sashMM = bar * 0.6;

    var ctx = { W: W, H: H, s: s, shape: shape, rise: rise, isDoor: isDoor, bar: bar };
    var outline = makeOutline(ctx);
    var outer = outline(0), inner = outline(bar);
    var rects = paneRects(design, ctx);

    var barPx = bar * s;
    var sashPx = sashMM * s;
    var grooveW = Math.max(1.2, barPx * 0.07);
    var beadPx = Math.max(1.5, sashPx * 0.28);

    /* layer canvas: R frame / G sash / B muntin */
    var layerCanvas = makeCanvas(cw, ch);
    var lg = layerCanvas.getContext('2d');
    lg.fillStyle = '#000'; lg.fillRect(0, 0, cw, ch);
    lg.fillStyle = 'rgb(0,255,0)';
    lg.fill(inner);
    lg.save();
    lg.clip(inner);
    rects.forEach(function (r) {
      lg.fillStyle = r.panel ? 'rgb(0,255,0)' : '#000';
      lg.fillRect(r.x, r.y, r.w, r.h);
    });
    var minThick = barPx;
    rects.forEach(function (r) {
      if (r.panel) return;
      (r.pane.glazingBars || []).forEach(function (gb) {
        var t = Math.max(2, (gb.thickness || 18) * s);
        minThick = Math.min(minThick, t);
        lg.save();
        lg.beginPath(); lg.rect(r.x, r.y, r.w, r.h); lg.clip();
        lg.fillStyle = 'rgb(0,0,255)';
        if (gb.type === 'vertical') lg.fillRect(r.x + r.w * gb.pos - t / 2, r.y, t, r.h);
        else lg.fillRect(r.x, r.y + r.h * gb.pos - t / 2, r.w, t);
        lg.restore();
      });
    });
    lg.restore();
    var ring = new Path2D();
    ring.addPath(outer); ring.addPath(inner);
    lg.fillStyle = 'rgb(255,0,0)';
    lg.fill(ring, 'evenodd');

    /* mask canvas: R glass / G panel / B inside outer shape */
    var maskCanvas = makeCanvas(cw, ch);
    var mg = maskCanvas.getContext('2d');
    mg.fillStyle = '#000'; mg.fillRect(0, 0, cw, ch);
    mg.fillStyle = 'rgb(0,0,255)';
    mg.fill(outer);
    mg.save();
    mg.clip(inner);
    rects.forEach(function (r) {
      mg.fillStyle = r.panel ? 'rgb(0,255,255)' : 'rgb(255,0,255)';
      mg.fillRect(r.x, r.y, r.w, r.h);
    });
    mg.restore();
    rects.forEach(function (r) {
      if (r.panel) return;
      (r.pane.glazingBars || []).forEach(function (gb) {
        var t = Math.max(2, (gb.thickness || 18) * s);
        mg.save();
        mg.beginPath(); mg.rect(r.x, r.y, r.w, r.h); mg.clip();
        mg.fillStyle = 'rgb(0,0,255)';
        if (gb.type === 'vertical') mg.fillRect(r.x + r.w * gb.pos - t / 2, r.y, t, r.h);
        else mg.fillRect(r.x, r.y + r.h * gb.pos - t / 2, r.w, t);
        mg.restore();
      });
    });

    /* height canvas: bevelled relief */
    var heightCanvas = makeCanvas(cw, ch);
    var hg = heightCanvas.getContext('2d');
    hg.fillStyle = gray(0); hg.fillRect(0, 0, cw, ch);
    hg.fillStyle = gray(HEIGHT.frame);
    hg.fill(outer);
    hg.fillStyle = gray(HEIGHT.sash);
    hg.fill(inner);
    hg.strokeStyle = gray(HEIGHT.groove);
    hg.lineWidth = grooveW;
    hg.stroke(inner);
    hg.save();
    hg.clip(inner);
    rects.forEach(function (r) {
      if (r.panel) {
        hg.fillStyle = gray(HEIGHT.panel);
        hg.fillRect(r.x, r.y, r.w, r.h);
        hg.strokeStyle = gray(HEIGHT.panelEdge);
        hg.lineWidth = Math.max(1.5, sashPx * 0.18);
        hg.strokeRect(r.x + r.w * 0.1, r.y + r.h * 0.06, r.w * 0.8, r.h * 0.88);
        return;
      }
      hg.fillStyle = gray(HEIGHT.bead);
      hg.fillRect(r.x - beadPx, r.y - beadPx, r.w + beadPx * 2, r.h + beadPx * 2);
      hg.fillStyle = gray(HEIGHT.glass);
      hg.fillRect(r.x, r.y, r.w, r.h);
      (r.pane.glazingBars || []).forEach(function (gb) {
        var t = Math.max(2, (gb.thickness || 18) * s);
        hg.save();
        hg.beginPath(); hg.rect(r.x, r.y, r.w, r.h); hg.clip();
        hg.fillStyle = gray(HEIGHT.muntin);
        if (gb.type === 'vertical') hg.fillRect(r.x + r.w * gb.pos - t / 2, r.y, t, r.h);
        else hg.fillRect(r.x, r.y + r.h * gb.pos - t / 2, r.w, t);
        hg.restore();
      });
    });
    hg.restore();
    var bevelR = Math.max(0.8, Math.min(6, minThick * 0.30));
    var softHeight = blurCanvas(heightCanvas, bevelR);

    var glassRects = rects.filter(function (r) { return !r.panel; }).map(function (r) {
      return [r.x / cw, r.y / ch, r.w / cw, r.h / ch];
    });

    var frameRGB = hexToRgb(frame.color, [0.17, 0.18, 0.20]);
    var sashRGB = hexToRgb(frame.sashColor, frameRGB);

    var fin = finishSpec(frame);
    var finishCanvas = null;
    if (fin) {
      if (fin.kind === 'wood') {
        frameRGB = hexToRgb(fin.wood.base, frameRGB);
        sashRGB = frameRGB;
      }
      finishCanvas = buildFinishCanvas(fin, frame, cw, ch, s, {
        shape: shape, bar: bar, rise: rise, barPx: barPx, sashPx: sashPx,
        inner: inner, rects: rects
      });
    }

    var result = {
      width: cw, height: ch,
      layerCanvas: layerCanvas,
      heightCanvas: softHeight,
      maskCanvas: maskCanvas,
      finishCanvas: finishCanvas,
      finish: fin ? { key: fin.key, kind: fin.kind, gloss: fin.gloss, metallic: fin.metallic,
                      roughness: 1 - fin.gloss } : null,
      colors: { frame: frameRGB, sash: sashRGB },
      metrics: {
        barPx: barPx, sashPx: sashPx, muntinPx: minThick, grooveW: grooveW, beadPx: beadPx,
        barUV: barPx / cw, bevelPx: bevelR,
        shape: shape, isDoor: isDoor, hasCill: !!frame.cill,
        widthMM: W, heightMM: H, glassRects: glassRects
      }
    };

    if (_cache.size >= CACHE_MAX) _cache.delete(_cache.keys().next().value);
    _cache.set(key, result);
    return result;
  }

  function clearCache() { _cache.clear(); }

  var api = { build: build, clearCache: clearCache, HEIGHT: HEIGHT };
  root.PhotorealLayers = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
