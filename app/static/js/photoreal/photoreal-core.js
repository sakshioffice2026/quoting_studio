/* app/static/js/photoreal/photoreal-core.js
 *
 * Single shared entry to the photoreal engine. Staff per-window view, project
 * scene view and customer public link all call PhotorealCore.paintOpening().
 *
 * Pipeline per opening:
 *   1. sample the wall on all sides (clean pixels, before anything is painted)
 *   2. lighting analysis from the photo (cached)
 *   3. hide the old window (feathered, texture preserving wall fill)
 *   4. dark room base behind the glass
 *   5. WebGL paint (tiled when available)
 *
 * Returns { ok, wall, lighting }. When ok is false nothing was drawn by the
 * WebGL pass (the caller keeps its own canvas fallback). The wall patch and
 * room base are only drawn when the WebGL pass is usable, so a failed call
 * leaves the canvas untouched.
 *
 * Usage:
 *   const res = PhotorealCore.paintOpening({
 *     ctx, width, height, quad, design, photo, stats, wall,
 *     options: {
 *       variant, lightOn, interiorBright, sill, reflect, yawDeg,
 *       opacity, brightness, intensity, life, glare, seed,
 *       hideOld, hideStrength
 *     }
 *   });
 *
 * Required globals (loaded by photoreal-loader.js):
 *   PhotorealLayers, PhotorealLighting, PhotorealInterior,
 *   PhotorealShaders, PhotorealRenderer
 */
(function (root) {
  'use strict';

  var photoIds = (typeof WeakMap !== 'undefined') ? new WeakMap() : null;
  var photoSeq = 0;
  var lightCache = { key: null, val: null };
  var designCache = new Map();
  var DESIGN_CACHE_MAX = 32;

  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

  function photoId(photo, stats) {
    if (stats && stats.id != null) return 's' + stats.id;
    if (!photo) return 'none';
    if (photoIds) {
      var id = photoIds.get(photo);
      if (!id) { id = ++photoSeq; photoIds.set(photo, id); }
      return 'p' + id + ':' + (photo.naturalWidth || photo.width) + 'x' + (photo.naturalHeight || photo.height);
    }
    return 'p:' + (photo.naturalWidth || photo.width) + 'x' + (photo.naturalHeight || photo.height);
  }

  function quadBox(q) {
    var xs = [q.tl.x, q.tr.x, q.bl.x, q.br.x];
    var ys = [q.tl.y, q.tr.y, q.bl.y, q.br.y];
    return {
      x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs),
      y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys)
    };
  }

  function centroid(q) {
    return {
      x: (q.tl.x + q.tr.x + q.bl.x + q.br.x) / 4,
      y: (q.tl.y + q.tr.y + q.bl.y + q.br.y) / 4
    };
  }

  function scaleQuad(q, k) {
    var c = centroid(q);
    function p(pt) { return { x: c.x + (pt.x - c.x) * k, y: c.y + (pt.y - c.y) * k }; }
    return { tl: p(q.tl), tr: p(q.tr), bl: p(q.bl), br: p(q.br) };
  }

  function quadPath(ctx, q) {
    ctx.beginPath();
    ctx.moveTo(q.tl.x, q.tl.y);
    ctx.lineTo(q.tr.x, q.tr.y);
    ctx.lineTo(q.br.x, q.br.y);
    ctx.lineTo(q.bl.x, q.bl.y);
    ctx.closePath();
  }

  function makeCanvas(w, h) {
    var c = document.createElement('canvas');
    c.width = Math.max(1, w); c.height = Math.max(1, h);
    return c;
  }

  function rgbCss(c) {
    return 'rgb(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ')';
  }

  /* ---------- readiness ---------- */
  function renderer() {
    return root.PhotorealRenderer ? root.PhotorealRenderer.get() : null;
  }

  function isReady() {
    var r = renderer();
    return !!(r && r.supported && !r.lost &&
      root.PhotorealLayers && root.PhotorealInterior &&
      root.PhotorealLighting && root.PhotorealShaders);
  }

  /* ---------- wall sampling: all four sides + corners ---------- */
  function samplePatch(ctx, x, y, P) {
    try {
      var cw = ctx.canvas.width, ch = ctx.canvas.height;
      var px = Math.round(clamp(x - P / 2, 0, Math.max(0, cw - P)));
      var py = Math.round(clamp(y - P / 2, 0, Math.max(0, ch - P)));
      var d = ctx.getImageData(px, py, P, P).data;
      var r = 0, g = 0, b = 0, n = 0;
      for (var i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
      return n ? [r / n, g / n, b / n] : null;
    } catch (e) { return null; }
  }

  function median3(list) {
    var out = [0, 0, 0];
    for (var k = 0; k < 3; k++) {
      var a = list.map(function (c) { return c[k]; }).sort(function (p, q) { return p - q; });
      var m = Math.floor(a.length / 2);
      out[k] = (a.length % 2) ? a[m] : (a[m - 1] + a[m]) / 2;
    }
    return out;
  }

  function sampleWall(ctx, quad) {
    var b = quadBox(quad);
    var bw = b.x1 - b.x0, bh = b.y1 - b.y0;
    var m = 10 + bw * 0.10, P = 6;
    var cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
    var got = {
      l: samplePatch(ctx, b.x0 - m, cy, P),
      r: samplePatch(ctx, b.x1 + m, cy, P),
      t: samplePatch(ctx, cx, b.y0 - m, P),
      b: samplePatch(ctx, cx, b.y1 + m, P),
      tl: samplePatch(ctx, b.x0 - m, b.y0 - m, P),
      tr: samplePatch(ctx, b.x1 + m, b.y0 - m, P),
      bl: samplePatch(ctx, b.x0 - m, b.y1 + m, P),
      br: samplePatch(ctx, b.x1 + m, b.y1 + m, P)
    };
    var list = [];
    for (var k in got) if (got[k]) list.push(got[k]);
    if (!list.length) {
      var def = [190, 180, 160];
      return { l: def, r: def, t: def, b: def, top: def, bot: def, mid: def, valid: false };
    }
    var mid = median3(list);
    function avg(a, c) {
      if (a && c) return [(a[0] + c[0]) / 2, (a[1] + c[1]) / 2, (a[2] + c[2]) / 2];
      return a || c || mid;
    }
    var wall = {
      l: got.l || mid, r: got.r || mid, t: got.t || mid, b: got.b || mid,
      mid: mid, valid: true
    };
    wall.top = avg(got.t, avg(got.tl, got.tr)) ;
    wall.bot = avg(got.b, avg(got.bl, got.br));
    if (got.t && (got.tl || got.tr)) wall.top = avg(got.t, avg(got.tl, got.tr));
    else wall.top = got.t || avg(got.tl, got.tr) || mid;
    if (got.b && (got.bl || got.br)) wall.bot = avg(got.b, avg(got.bl, got.br));
    else wall.bot = got.b || avg(got.bl, got.br) || mid;
    return wall;
  }

  /* ---------- lighting (cached per photo + wall) ---------- */
  function lightingFor(o, wall) {
    var wk = wall && wall.mid ? wall.mid.map(Math.round).join(',') : '-';
    var b = quadBox(o.quad);
    var qk = [Math.round(b.x0 / 8), Math.round(b.y0 / 8), Math.round(b.x1 / 8), Math.round(b.y1 / 8)].join(',');
    var key = photoId(o.photo, o.stats) + '|' + wk + '|' + qk + '|' + o.width + 'x' + o.height;
    if (lightCache.key === key && lightCache.val) return lightCache.val;
    var L = root.PhotorealLighting.analyze({
      photo: o.photo || o.ctx.canvas,
      ctx: o.ctx,
      quad: o.quad,
      stats: o.stats || {}
    });
    if (wall && wall.mid) {
      L.wall = [wall.mid[0] / 255, wall.mid[1] / 255, wall.mid[2] / 255];
    }
    lightCache.key = key; lightCache.val = L;
    return L;
  }

  /* ---------- design metrics (hasCill drives the sill) ---------- */
  function metricsFor(design) {
    var key;
    try { key = JSON.stringify(design); } catch (e) { key = null; }
    if (key && designCache.has(key)) return designCache.get(key);
    var m = null;
    try { m = root.PhotorealLayers.build(design, { maxSize: 256 }).metrics; } catch (e) { m = null; }
    if (key) {
      if (designCache.size >= DESIGN_CACHE_MAX) designCache.delete(designCache.keys().next().value);
      designCache.set(key, m);
    }
    return m;
  }

  /* ---------- hide the old window: feathered, texture preserving ---------- */
  function strip(srcCanvas, sx, sy, sw, sh, dw, dh) {
    var c = makeCanvas(dw, dh);
    c.getContext('2d').drawImage(srcCanvas, sx, sy, sw, sh, 0, 0, dw, dh);
    return c;
  }

  function fadeAlpha(canvas, horizontal, fromOne) {
    var g = canvas.getContext('2d');
    var grad = horizontal
      ? g.createLinearGradient(0, 0, canvas.width, 0)
      : g.createLinearGradient(0, 0, 0, canvas.height);
    grad.addColorStop(0, 'rgba(0,0,0,' + (fromOne ? 1 : 0) + ')');
    grad.addColorStop(1, 'rgba(0,0,0,' + (fromOne ? 0 : 1) + ')');
    g.globalCompositeOperation = 'destination-in';
    g.fillStyle = grad;
    g.fillRect(0, 0, canvas.width, canvas.height);
    g.globalCompositeOperation = 'source-over';
  }

  function hideOldWindow(ctx, quad, wall, alpha, strength) {
    if (alpha <= 0.001) return false;
    var cw = ctx.canvas.width, ch = ctx.canvas.height;
    var q = scaleQuad(quad, 1.07);
    var b = quadBox(q);
    var feather = Math.max(2, Math.min(b.x1 - b.x0, b.y1 - b.y0) * 0.04);
    var pad = Math.ceil(feather * 2);

    var bx = Math.max(0, Math.floor(b.x0 - pad)), by = Math.max(0, Math.floor(b.y0 - pad));
    var bx2 = Math.min(cw, Math.ceil(b.x1 + pad)), by2 = Math.min(ch, Math.ceil(b.y1 + pad));
    var bw = bx2 - bx, bh = by2 - by;
    if (bw < 4 || bh < 4 || bw * bh > 16000000) return false;

    var sw = Math.max(4, Math.round(Math.min(bw, bh) * 0.06));
    var gap = Math.max(2, Math.round(sw * 0.5));
    var src = ctx.canvas;

    /* wall-colour base so invalid strips never leave holes */
    var patch = makeCanvas(bw, bh);
    var pg = patch.getContext('2d');
    var base = pg.createLinearGradient(0, 0, 0, bh);
    base.addColorStop(0, rgbCss(wall.top || wall.mid));
    base.addColorStop(1, rgbCss(wall.bot || wall.mid));
    pg.fillStyle = base;
    pg.fillRect(0, 0, bw, bh);

    /* horizontal fill: left and right strips stretched across, linear weights */
    var lx = bx - gap - sw, rx = bx2 + gap;
    var hasL = lx >= 0, hasR = rx + sw <= cw;
    var H = makeCanvas(bw, bh), hg = H.getContext('2d');
    var hCount = 0;
    if (hasL) {
      var L = strip(src, lx, by, sw, bh, bw, bh);
      if (hasR) fadeAlpha(L, true, true);
      hg.globalCompositeOperation = 'lighter'; hg.drawImage(L, 0, 0); hCount++;
    }
    if (hasR) {
      var R = strip(src, rx, by, sw, bh, bw, bh);
      if (hasL) fadeAlpha(R, true, false);
      hg.globalCompositeOperation = 'lighter'; hg.drawImage(R, 0, 0); hCount++;
    }

    /* vertical fill: top and bottom strips */
    var ty = by - gap - sw, byy = by2 + gap;
    var hasT = ty >= 0, hasB = byy + sw <= ch;
    var V = makeCanvas(bw, bh), vg = V.getContext('2d');
    var vCount = 0;
    if (hasT) {
      var T = strip(src, bx, ty, bw, sw, bw, bh);
      if (hasB) fadeAlpha(T, false, true);
      vg.globalCompositeOperation = 'lighter'; vg.drawImage(T, 0, 0); vCount++;
    }
    if (hasB) {
      var B = strip(src, bx, byy, bw, sw, bw, bh);
      if (hasT) fadeAlpha(B, false, false);
      vg.globalCompositeOperation = 'lighter'; vg.drawImage(B, 0, 0); vCount++;
    }

    if (hCount && vCount) {
      pg.globalAlpha = 1; pg.drawImage(H, 0, 0);
      pg.globalAlpha = 0.5; pg.drawImage(V, 0, 0);
      pg.globalAlpha = 1;
    } else if (hCount) {
      pg.drawImage(H, 0, 0);
    } else if (vCount) {
      pg.drawImage(V, 0, 0);
    }

    /* feathered quad mask (shadow trick works everywhere) */
    var mask = makeCanvas(bw, bh), mg = mask.getContext('2d');
    var OFF = bw + bh + 200;
    mg.save();
    mg.translate(-bx - OFF, -by);
    mg.shadowColor = '#000';
    mg.shadowBlur = feather;
    mg.shadowOffsetX = OFF;
    mg.shadowOffsetY = 0;
    mg.fillStyle = '#000';
    quadPath(mg, q);
    mg.fill();
    mg.restore();

    pg.globalCompositeOperation = 'destination-in';
    pg.drawImage(mask, 0, 0);
    pg.globalCompositeOperation = 'source-over';

    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = clamp(alpha * (strength != null ? strength : 0.96), 0, 1);
    ctx.drawImage(patch, bx, by);
    ctx.restore();
    return true;
  }

  /* ---------- dark room behind the glass ---------- */
  function roomBase(ctx, quad, alpha) {
    if (alpha <= 0.001) return;
    var b = quadBox(quad);
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = alpha;
    var room = ctx.createLinearGradient(0, b.y0, 0, b.y1);
    room.addColorStop(0, '#2d2924');
    room.addColorStop(0.55, '#1d1a16');
    room.addColorStop(1, '#0f0d0b');
    ctx.fillStyle = room;
    quadPath(ctx, quad);
    ctx.fill();
    ctx.restore();
  }

  /* ---------- main entry ---------- */
  function paintOpening(o) {
    var out = { ok: false, wall: null, lighting: null };
    if (!o || !o.ctx || !o.quad || !o.design) return out;
    if (!isReady()) return out;

    var opt = o.options || {};
    var ctx = o.ctx;
    o.width = o.width || ctx.canvas.width;
    o.height = o.height || ctx.canvas.height;

    var life = opt.life != null ? opt.life : 1;
    var wall = o.wall && o.wall.mid ? o.wall : sampleWall(ctx, o.quad);
    var lighting;
    try { lighting = lightingFor(o, wall); } catch (e) { return out; }

    var metrics = metricsFor(o.design);
    var sill = opt.sill != null ? !!opt.sill : !!(metrics && metrics.hasCill);
    if (metrics && metrics.isDoor) sill = false;

    var r = renderer();
    var paint = r.paintTiled ? 'paintTiled' : 'paint';

    /* snapshot so a failed WebGL pass leaves the canvas exactly as it was */
    var b = quadBox(o.quad);
    var mx = (b.x1 - b.x0) * 0.5, my = (b.y1 - b.y0) * 0.5;
    var sx = Math.max(0, Math.floor(b.x0 - mx)), sy = Math.max(0, Math.floor(b.y0 - my));
    var sx2 = Math.min(o.width, Math.ceil(b.x1 + mx)), sy2 = Math.min(o.height, Math.ceil(b.y1 + my));
    var snap = null;
    if (sx2 - sx > 2 && sy2 - sy > 2) {
      snap = makeCanvas(sx2 - sx, sy2 - sy);
      snap.getContext('2d').drawImage(ctx.canvas, sx, sy, sx2 - sx, sy2 - sy, 0, 0, sx2 - sx, sy2 - sy);
    }

    if (opt.hideOld !== false) hideOldWindow(ctx, o.quad, wall, life, opt.hideStrength);
    roomBase(ctx, o.quad, life);

    var ok = r[paint](ctx, o.width, o.height, o.quad, {
      design: o.design,
      lighting: lighting,
      reflect: opt.reflect != null ? opt.reflect : 0.5,
      yawDeg: opt.yawDeg || 0,
      opacity: opt.opacity != null ? opt.opacity : 0.92,
      brightness: opt.brightness != null ? opt.brightness : 1,
      intensity: opt.intensity != null ? opt.intensity : 0.7,
      life: life,
      glare: opt.glare != null ? opt.glare : -1,
      seed: opt.seed != null ? opt.seed : 1,
      variant: opt.variant || 'auto',
      lightOn: opt.lightOn !== false,
      interiorBright: opt.interiorBright != null ? opt.interiorBright : 0.85,
      sill: sill
    });

    if (!ok && snap) {
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
      ctx.clearRect(sx, sy, snap.width, snap.height);
      ctx.drawImage(snap, sx, sy);
      ctx.restore();
    }

    out.ok = !!ok;
    out.wall = wall;
    out.lighting = lighting;
    return out;
  }

  /* paint many openings in order; returns array of results */
  function paintAll(ctx, width, height, openings, common) {
    var res = [];
    (openings || []).forEach(function (op) {
      var args = {};
      var k;
      for (k in common) if (Object.prototype.hasOwnProperty.call(common, k)) args[k] = common[k];
      for (k in op) if (Object.prototype.hasOwnProperty.call(op, k)) args[k] = op[k];
      args.ctx = ctx; args.width = width; args.height = height;
      res.push(paintOpening(args));
    });
    return res;
  }

  function clearCaches() {
    lightCache.key = null; lightCache.val = null;
    designCache.clear();
  }

  var api = {
    isReady: isReady,
    paintOpening: paintOpening,
    paintAll: paintAll,
    sampleWall: sampleWall,
    hideOldWindow: hideOldWindow,
    roomBase: roomBase,
    clearCaches: clearCaches
  };
  root.PhotorealCore = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
