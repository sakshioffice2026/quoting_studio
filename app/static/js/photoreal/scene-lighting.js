/* app/static/js/photoreal/scene-lighting.js
 *
 * Reads the background photograph and returns lighting parameters used by the
 * photoreal shader: light direction, sun/shadow tint, colour temperature,
 * overcast factor, wall colours around the opening, reflection environment
 * bands, grain.
 *
 * It extends (does not replace) the existing _sceneStats() result:
 *   stats = { gain:[r,g,b], sky:[r,g,b], lightX:-1|1, grain, id }
 *
 * Usage:
 *   const L = PhotorealLighting.analyze({ photo, ctx, quad, stats });
 *   const U = PhotorealLighting.toUniforms(L);
 */
(function (root) {
  'use strict';

  var SCENE_W = 96;
  var BANDS = 6;
  var _cache = { key: null, scene: null };
  var _seq = 0;

  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function lum(r, g, b) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
  function norm3(v) {
    var l = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / l, v[1] / l, v[2] / l];
  }
  function mix3(a, b, t) {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  }
  function tintOf(rgb, lo, hi) {
    var l = lum(rgb[0], rgb[1], rgb[2]) || 1;
    return [
      clamp(rgb[0] / l, lo, hi),
      clamp(rgb[1] / l, lo, hi),
      clamp(rgb[2] / l, lo, hi)
    ];
  }

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

  /* ---------- whole-photo statistics (cached per photo) ---------- */
  function analyzeScene(photo) {
    var pw = photo.naturalWidth || photo.width, ph = photo.naturalHeight || photo.height;
    var W = SCENE_W, H = Math.max(24, Math.round(W * ph / pw));
    var c = document.createElement('canvas');
    c.width = W; c.height = H;
    var g = c.getContext('2d', { willReadFrequently: true });
    g.drawImage(photo, 0, 0, W, H);
    var d = g.getImageData(0, 0, W, H).data;

    var hist = new Uint32Array(256);
    var sum = [0, 0, 0], n = 0, lsum = 0, lsq = 0;
    var third = [0, 0, 0], thirdN = [0, 0, 0];
    var vthird = [0, 0, 0], vthirdN = [0, 0, 0];
    var bands = [];
    var bandN = [];
    var sky = [0, 0, 0], skyN = 0;
    var b;
    for (b = 0; b < BANDS; b++) { bands.push([0, 0, 0]); bandN.push(0); }

    var x, y, i, R, G, B, l;
    for (y = 0; y < H; y++) {
      for (x = 0; x < W; x++) {
        i = (y * W + x) * 4;
        R = d[i]; G = d[i + 1]; B = d[i + 2];
        l = lum(R, G, B);
        hist[Math.min(255, Math.round(l))]++;
        sum[0] += R; sum[1] += G; sum[2] += B; n++;
        lsum += l; lsq += l * l;
        var tx = Math.min(2, Math.floor(x / (W / 3)));
        third[tx] += l; thirdN[tx]++;
        var ty = Math.min(2, Math.floor(y / (H / 3)));
        vthird[ty] += l; vthirdN[ty]++;
        var bi = Math.min(BANDS - 1, Math.floor(y / H * BANDS));
        bands[bi][0] += R; bands[bi][1] += G; bands[bi][2] += B; bandN[bi]++;
        if (y < H * 0.10) { sky[0] += R; sky[1] += G; sky[2] += B; skyN++; }
      }
    }
    var mean = [sum[0] / n, sum[1] / n, sum[2] / n];
    var lMean = lsum / n || 1;
    var lStd = Math.sqrt(Math.max(0, lsq / n - lMean * lMean));

    /* sun colour = average of brightest 5 % of pixels that are not near-white */
    var target = Math.floor(n * 0.05), got = 0, thr = 255;
    for (thr = 255; thr > 0 && got < target; thr--) got += hist[thr];
    var sr = 0, sg = 0, sb = 0, sn = 0;
    for (y = 0; y < H; y++) {
      for (x = 0; x < W; x++) {
        i = (y * W + x) * 4;
        l = lum(d[i], d[i + 1], d[i + 2]);
        if (l >= thr && l < 250) { sr += d[i]; sg += d[i + 1]; sb += d[i + 2]; sn++; }
      }
    }
    var sun = sn ? [sr / sn, sg / sn, sb / sn] : mean.slice();

    var envBands = bands.map(function (v, k) {
      var m = bandN[k] || 1;
      return [v[0] / m / 255, v[1] / m / 255, v[2] / m / 255];
    });

    return {
      mean: mean, lMean: lMean, lStd: lStd,
      lumL: third[0] / (thirdN[0] || 1), lumR: third[2] / (thirdN[2] || 1),
      lumT: vthird[0] / (vthirdN[0] || 1), lumB: vthird[2] / (vthirdN[2] || 1),
      sun: sun,
      sky: skyN ? [sky[0] / skyN, sky[1] / skyN, sky[2] / skyN] : [150, 185, 215],
      envBands: envBands
    };
  }

  /* ---------- wall ring around the opening ---------- */
  function ringColors(ctx, quad) {
    if (!ctx || !quad) return null;
    var xs = [quad.tl.x, quad.tr.x, quad.bl.x, quad.br.x];
    var ys = [quad.tl.y, quad.tr.y, quad.bl.y, quad.br.y];
    var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs);
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    var m = 10 + (x1 - x0) * 0.10, P = 6, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    var out = {
      l: samplePatch(ctx, x0 - m, cy, P),
      r: samplePatch(ctx, x1 + m, cy, P),
      t: samplePatch(ctx, cx, y0 - m, P),
      b: samplePatch(ctx, cx, y1 + m, P)
    };
    var list = [out.l, out.r, out.t, out.b].filter(Boolean);
    if (!list.length) return null;
    var med = function (k) {
      var a = list.map(function (c) { return c[k]; }).sort(function (p, q) { return p - q; });
      return a[Math.floor(a.length / 2)];
    };
    out.mid = [med(0), med(1), med(2)];
    out.l = out.l || out.mid; out.r = out.r || out.mid;
    out.t = out.t || out.mid; out.b = out.b || out.mid;
    return out;
  }

  /* ---------- main ---------- */
  function analyze(o) {
    o = o || {};
    var stats = o.stats || {};
    var scene = null;

    if (o.photo) {
      var key = (stats.id != null ? 'id' + stats.id : 'p') + ':' +
        (o.photo.naturalWidth || o.photo.width) + 'x' + (o.photo.naturalHeight || o.photo.height);
      if (_cache.key === key && _cache.scene) scene = _cache.scene;
      else {
        try { scene = analyzeScene(o.photo); _cache.key = key; _cache.scene = scene; }
        catch (e) { scene = null; }
      }
    }

    var lMean = scene ? scene.lMean : 140;
    var mean = scene ? scene.mean : [150, 150, 150];
    var sky = scene ? scene.sky : (stats.sky || [150, 185, 215]);
    var sun = scene ? scene.sun : [235, 228, 215];

    /* colour temperature (approximate kelvin from sun warmth) */
    var warmth = clamp((sun[0] - sun[2]) / (sun[0] + sun[2] + 1) * 2.2, -1, 1);
    var kelvin = Math.round(clamp(6500 - warmth * 3000, 3500, 9000));

    /* overcast: flat contrast + no left/right bias */
    var sideDiff = scene ? Math.abs(scene.lumL - scene.lumR) / lMean : 0.1;
    var contrast = scene ? scene.lStd / lMean : 0.35;
    var overcast = clamp(1 - (contrast * 1.5 + sideDiff * 2.4), 0, 1);
    var sunStrength = clamp(1 - overcast * 0.85, 0.15, 1);

    /* light direction: toward the light, screen space, x<0 = from the left */
    var lx = scene ? clamp((scene.lumR - scene.lumL) / lMean * 2.2, -1, 1) : 0;
    if (Math.abs(lx) < 0.12) lx = (stats.lightX || -1) * 0.45;
    var ring = ringColors(o.ctx, o.quad);
    if (ring) {
      var ll = lum(ring.l[0], ring.l[1], ring.l[2]);
      var rl = lum(ring.r[0], ring.r[1], ring.r[2]);
      var local = clamp((rl - ll) / ((ll + rl) / 2 + 1) * 3, -1, 1);
      lx = lx * 0.4 + local * 0.6;
    }
    var ly = -clamp(0.40 + (scene ? (scene.lumT - scene.lumB) / lMean * 0.5 : 0), 0.2, 0.9);
    var lightDir = norm3([lx, ly, 0.55 + overcast * 0.35]);

    /* shadow cast by the frame onto the wall */
    var sdir = norm3([-lightDir[0], -lightDir[1], 0.001]);
    var shadow = {
      dir: [sdir[0], sdir[1]],
      softness: clamp(0.025 + overcast * 0.09, 0.02, 0.12),
      strength: clamp(0.18 + sunStrength * 0.34, 0.15, 0.55),
      length: clamp(0.012 + (1 - Math.abs(lightDir[2])) * 0.03, 0.008, 0.04)
    };

    var skyN = [sky[0] / 255, sky[1] / 255, sky[2] / 255];
    var sunTint = tintOf(mix3(sun, [255, 255, 255], 0.25), 0.78, 1.22);
    var shadowTint = mix3(tintOf(sky, 0.7, 1.3), [1, 1, 1], 0.45);
    var wall = ring ? ring.mid : mean;

    var gain = stats.gain || [1, 1, 1];
    var envBands = scene ? scene.envBands : [];
    while (envBands.length < BANDS) envBands.push(skyN);

    return {
      id: ++_seq,
      lightDir: lightDir,
      sunTint: sunTint,
      shadowTint: shadowTint,
      sunStrength: sunStrength,
      overcast: overcast,
      warmth: warmth,
      kelvin: kelvin,
      exposure: clamp(lMean / 255, 0.1, 1),
      ambient: [skyN[0] * 0.55 + 0.25, skyN[1] * 0.55 + 0.25, skyN[2] * 0.55 + 0.25],
      sky: skyN,
      wall: [wall[0] / 255, wall[1] / 255, wall[2] / 255],
      ring: ring,
      envBands: envBands,
      shadow: shadow,
      gain: gain,
      grain: stats.grain != null ? stats.grain : 1.2
    };
  }

  function flatten(arr) {
    var out = [];
    arr.forEach(function (v) { out.push(v[0], v[1], v[2]); });
    return new Float32Array(out);
  }

  /* uniform-ready values for the renderer */
  function toUniforms(L) {
    return {
      uLightDir: new Float32Array(L.lightDir),
      uSunTint: new Float32Array(L.sunTint),
      uShadowTint: new Float32Array(L.shadowTint),
      uSunStrength: L.sunStrength,
      uOvercast: L.overcast,
      uAmbient: new Float32Array(L.ambient),
      uSky: new Float32Array(L.sky),
      uWall: new Float32Array(L.wall),
      uEnv: flatten(L.envBands.slice(0, BANDS)),
      uGain: new Float32Array(L.gain),
      uGrain: L.grain,
      uExposure: L.exposure,
      uShadowDir: new Float32Array(L.shadow.dir),
      uShadowSoft: L.shadow.softness,
      uShadowStrength: L.shadow.strength,
      uShadowLen: L.shadow.length
    };
  }

  var api = { analyze: analyze, toUniforms: toUniforms, BANDS: BANDS };
  root.PhotorealLighting = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
