/* app/static/js/photoreal/interior-gen.js
 *
 * Procedural interior seen through the glass. Returns three layered canvases
 * so the shader can apply a small parallax between them (room depth):
 *
 *   far  : opaque back wall, ceiling, floor, light pools
 *   mid  : transparent furniture / shelves / table silhouettes
 *   near : transparent curtains, chandelier / pendant lights
 *
 * Usage:
 *   const R = PhotorealInterior.build({ variant:'auto', seed:7, lightOn:true, warmth:0.2 });
 *   R.far / R.mid / R.near  (HTMLCanvasElement, 512x512)
 */
(function (root) {
  'use strict';

  var S = 512;
  var _cache = new Map();

  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function mk() {
    var c = document.createElement('canvas');
    c.width = S; c.height = S;
    return c;
  }

  function rr(g, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function glow(g, x, y, r, rgb, a) {
    var gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, 'rgba(' + rgb + ',' + a + ')');
    gr.addColorStop(0.35, 'rgba(' + rgb + ',' + (a * 0.35) + ')');
    gr.addColorStop(1, 'rgba(' + rgb + ',0)');
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }

  function shade(rgb, k) {
    return 'rgb(' + rgb.map(function (v) { return Math.max(0, Math.min(255, Math.round(v * k))); }).join(',') + ')';
  }

  var PALETTES = {
    living:  { wall: [196, 178, 150], ceil: [214, 206, 192], floor: [92, 66, 44],  accent: [96, 112, 92]  },
    dining:  { wall: [176, 162, 140], ceil: [208, 200, 186], floor: [74, 52, 36],  accent: [120, 70, 60]  },
    bedroom: { wall: [170, 176, 178], ceil: [212, 214, 214], floor: [110, 96, 80], accent: [128, 138, 160] },
    study:   { wall: [128, 112, 92],  ceil: [170, 160, 146], floor: [58, 42, 30],  accent: [90, 54, 44]   }
  };
  var VARIANTS = ['living', 'dining', 'bedroom', 'study'];

  /* ---------------- far layer ---------------- */
  function drawFar(g, P, R, o) {
    var horizon = S * (0.60 + R() * 0.05);
    var ceilY = S * (0.10 + R() * 0.05);

    var wall = g.createLinearGradient(0, ceilY, 0, horizon);
    wall.addColorStop(0, shade(P.wall, 0.78));
    wall.addColorStop(0.5, shade(P.wall, 0.95));
    wall.addColorStop(1, shade(P.wall, 0.70));
    g.fillStyle = wall; g.fillRect(0, 0, S, horizon);

    var ceil = g.createLinearGradient(0, 0, 0, ceilY);
    ceil.addColorStop(0, shade(P.ceil, 0.88));
    ceil.addColorStop(1, shade(P.ceil, 0.70));
    g.fillStyle = ceil; g.fillRect(0, 0, S, ceilY);

    var floor = g.createLinearGradient(0, horizon, 0, S);
    floor.addColorStop(0, shade(P.floor, 0.80));
    floor.addColorStop(1, shade(P.floor, 0.35));
    g.fillStyle = floor; g.fillRect(0, horizon, S, S - horizon);

    /* floorboards in perspective */
    g.strokeStyle = 'rgba(0,0,0,0.18)'; g.lineWidth = 1;
    for (var i = -8; i <= 8; i++) {
      g.beginPath();
      g.moveTo(S / 2 + i * 10, horizon);
      g.lineTo(S / 2 + i * 70, S);
      g.stroke();
    }

    /* skirting + picture frames + door opening on the back wall */
    g.fillStyle = shade(P.ceil, 0.55);
    g.fillRect(0, horizon - 10, S, 10);
    var frames = 1 + Math.floor(R() * 3);
    for (var f = 0; f < frames; f++) {
      var fw = 40 + R() * 60, fh = 30 + R() * 56;
      var fx = 50 + R() * (S - 100 - fw), fy = ceilY + 24 + R() * 40;
      g.fillStyle = 'rgba(30,22,14,0.85)'; g.fillRect(fx - 3, fy - 3, fw + 6, fh + 6);
      g.fillStyle = shade(P.accent, 0.6 + R() * 0.4); g.fillRect(fx, fy, fw, fh);
    }
    if (R() > 0.45) {
      var dx = R() > 0.5 ? S * 0.06 : S * 0.76;
      g.fillStyle = 'rgba(14,10,8,0.82)';
      g.fillRect(dx, ceilY + 18, S * 0.18, horizon - ceilY - 28);
      glow(g, dx + S * 0.09, horizon - 40, 90, '255,214,150', 0.12);
    }

    /* warm light pools */
    var warm = o.warmth > 0 ? '255,206,140' : '240,214,170';
    if (o.lightOn) {
      glow(g, S * (0.35 + R() * 0.3), ceilY + 20, 260, warm, 0.34);
      glow(g, S * 0.5, horizon + 30, 220, warm, 0.14);
    }

    /* vignette = interior falloff */
    var v = g.createRadialGradient(S / 2, S * 0.55, S * 0.15, S / 2, S * 0.55, S * 0.78);
    v.addColorStop(0, 'rgba(0,0,0,0)');
    v.addColorStop(1, 'rgba(0,0,0,0.55)');
    g.fillStyle = v; g.fillRect(0, 0, S, S);
    return { horizon: horizon, ceilY: ceilY };
  }

  /* ---------------- mid layer ---------------- */
  function sofa(g, x, y, w, h, col) {
    g.fillStyle = shade(col, 0.55); rr(g, x, y - h * 0.55, w, h * 0.55, 10); g.fill();
    g.fillStyle = shade(col, 0.75); rr(g, x - 8, y - h * 0.30, w + 16, h * 0.30, 8); g.fill();
    g.fillStyle = shade(col, 0.50); rr(g, x - 10, y - h * 0.50, 20, h * 0.55, 8); g.fill();
    rr(g, x + w - 10, y - h * 0.50, 20, h * 0.55, 8); g.fill();
    g.fillStyle = 'rgba(255,255,255,0.10)'; g.fillRect(x + 6, y - h * 0.54, w - 12, 2);
  }

  function bookshelf(g, x, y, w, h, R) {
    g.fillStyle = 'rgba(28,20,14,0.92)'; g.fillRect(x, y, w, h);
    var rows = 4, rh = h / rows;
    for (var r = 0; r < rows; r++) {
      var bx = x + 4;
      while (bx < x + w - 8) {
        var bw = 4 + R() * 7, bh = rh * (0.55 + R() * 0.35);
        g.fillStyle = 'hsl(' + Math.floor(R() * 360) + ',' + Math.floor(20 + R() * 35) + '%,' + Math.floor(22 + R() * 26) + '%)';
        g.fillRect(bx, y + (r + 1) * rh - bh - 2, bw, bh);
        bx += bw + 1;
      }
      g.fillStyle = 'rgba(0,0,0,0.9)'; g.fillRect(x, y + (r + 1) * rh - 2, w, 3);
    }
  }

  function table(g, x, y, w, col, R) {
    g.fillStyle = shade(col, 0.55); g.fillRect(x, y, w, 7);
    g.fillRect(x + 8, y, 5, 52); g.fillRect(x + w - 13, y, 5, 52);
    for (var i = 0; i < 4; i++) {
      var cx = x + 14 + i * ((w - 40) / 3);
      g.fillStyle = shade(col, 0.42);
      rr(g, cx, y + 14, 18, 36, 4); g.fill();
      g.fillRect(cx + 1, y + 50, 3, 20); g.fillRect(cx + 14, y + 50, 3, 20);
    }
    g.fillStyle = 'rgba(230,220,200,0.35)';
    rr(g, x + w / 2 - 12, y - 14, 24, 14, 5); g.fill();
    g.fillStyle = 'rgba(40,90,50,0.85)'; g.beginPath(); g.arc(x + w * 0.28, y - 12, 9, 0, Math.PI * 2); g.fill();
  }

  function lamp(g, x, y, on) {
    g.fillStyle = 'rgba(24,18,12,0.9)'; g.fillRect(x - 2, y, 4, 58);
    g.fillRect(x - 12, y + 56, 24, 5);
    g.fillStyle = on ? 'rgba(255,228,170,0.95)' : 'rgba(190,176,150,0.85)';
    g.beginPath(); g.moveTo(x - 16, y); g.lineTo(x + 16, y); g.lineTo(x + 10, y - 22); g.lineTo(x - 10, y - 22); g.closePath(); g.fill();
    if (on) glow(g, x, y - 8, 90, '255,214,150', 0.55);
  }

  function plant(g, x, y, R) {
    g.fillStyle = 'rgba(40,24,16,0.9)'; rr(g, x - 12, y, 24, 22, 4); g.fill();
    g.fillStyle = 'rgba(20,52,30,0.9)';
    for (var i = 0; i < 9; i++) {
      var a = -Math.PI / 2 + (R() - 0.5) * 2.2, len = 26 + R() * 34;
      g.beginPath(); g.ellipse(x + Math.cos(a) * len * 0.5, y - 4 + Math.sin(a) * len * 0.5, 7, len * 0.5, a + Math.PI / 2, 0, Math.PI * 2); g.fill();
    }
  }

  function drawMid(g, P, R, geo, variant, o) {
    var y = geo.horizon + 34;
    if (variant === 'living') {
      sofa(g, S * (0.12 + R() * 0.1), y + 24, S * 0.42, 76, P.accent);
      lamp(g, S * 0.80, y - 40, o.lightOn);
      plant(g, S * 0.90, y + 14, R);
    } else if (variant === 'dining') {
      table(g, S * 0.18, y - 6, S * 0.56, [110, 74, 48], R);
      lamp(g, S * 0.86, y - 36, o.lightOn);
    } else if (variant === 'bedroom') {
      g.fillStyle = shade([150, 150, 160], 0.55); rr(g, S * 0.14, y - 34, S * 0.5, 62, 8); g.fill();
      g.fillStyle = shade(P.accent, 0.8); rr(g, S * 0.14, y - 46, S * 0.5, 20, 8); g.fill();
      g.fillStyle = 'rgba(255,255,255,0.18)'; rr(g, S * 0.17, y - 52, 70, 14, 6); g.fill();
      lamp(g, S * 0.76, y - 20, o.lightOn);
    } else {
      bookshelf(g, S * 0.08, geo.ceilY + 30, S * 0.30, geo.horizon - geo.ceilY - 30, R);
      bookshelf(g, S * 0.62, geo.ceilY + 30, S * 0.30, geo.horizon - geo.ceilY - 30, R);
      table(g, S * 0.30, y + 6, S * 0.40, [90, 56, 36], R);
    }
  }

  /* ---------------- near layer ---------------- */
  function curtain(g, x, w, top, bot, col, side) {
    var gr = g.createLinearGradient(x, 0, x + w, 0);
    var a = shade(col, 0.40), b = shade(col, 0.82);
    for (var i = 0; i <= 6; i++) gr.addColorStop(i / 6, i % 2 ? a : b);
    g.fillStyle = gr;
    g.beginPath();
    g.moveTo(x, top);
    g.lineTo(x + w, top);
    g.lineTo(x + w * (side < 0 ? 0.85 : 1.1), bot);
    g.lineTo(x - w * (side < 0 ? 0.1 : 0.15), bot);
    g.closePath(); g.fill();
    g.fillStyle = 'rgba(0,0,0,0.5)'; g.fillRect(x - 4, top - 6, w + 8, 8);
  }

  function chandelier(g, cx, cy, size, on, R) {
    g.strokeStyle = 'rgba(30,22,14,0.9)'; g.lineWidth = 2;
    g.beginPath(); g.moveTo(cx, 0); g.lineTo(cx, cy - size * 0.55); g.stroke();
    var arms = 5, bulbs = [];
    for (var i = 0; i < arms; i++) {
      var t = i / (arms - 1) * 2 - 1;
      var ax = cx + t * size, ay = cy + Math.abs(t) * size * 0.35;
      g.beginPath(); g.moveTo(cx, cy - size * 0.35);
      g.quadraticCurveTo(cx + t * size * 0.5, cy + size * 0.35, ax, ay); g.stroke();
      bulbs.push([ax, ay]);
    }
    g.fillStyle = 'rgba(40,30,18,0.95)';
    g.beginPath(); g.ellipse(cx, cy - size * 0.35, size * 0.12, size * 0.16, 0, 0, Math.PI * 2); g.fill();
    bulbs.forEach(function (b) {
      g.fillStyle = on ? 'rgba(255,236,190,1)' : 'rgba(200,190,170,0.85)';
      g.beginPath(); g.ellipse(b[0], b[1] - 7, 4, 7, 0, 0, Math.PI * 2); g.fill();
      if (on) glow(g, b[0], b[1] - 6, size * 0.9, '255,214,150', 0.5);
    });
    if (on) glow(g, cx, cy, size * 2.4, '255,220,160', 0.25);
    /* crystal drops */
    g.fillStyle = 'rgba(255,255,255,0.55)';
    for (var d = 0; d < 9; d++) {
      var dx = cx + (d - 4) * (size / 4), dy = cy + size * 0.35 + R() * 8;
      g.fillRect(dx, dy, 2, 6 + R() * 6);
    }
  }

  function drawNear(g, P, R, geo, variant, o) {
    var hasCurtains = R() > 0.35;
    if (hasCurtains) {
      var cw = S * (0.11 + R() * 0.05);
      curtain(g, 0, cw, 8, S * 0.98, P.accent, -1);
      curtain(g, S - cw, cw, 8, S * 0.98, P.accent, 1);
    }
    if (variant === 'dining' || variant === 'living' || R() > 0.6) {
      chandelier(g, S * (0.42 + R() * 0.16), geo.ceilY + 70 + R() * 24, 46 + R() * 24, o.lightOn, R);
    }
  }

  /* ---------------- main ---------------- */
  function build(opts) {
    opts = opts || {};
    var seed = opts.seed != null ? opts.seed : 1;
    var variant = opts.variant && opts.variant !== 'auto' ? opts.variant
      : VARIANTS[Math.floor(rng(seed * 7919)() * VARIANTS.length)];
    var o = { lightOn: opts.lightOn !== false, warmth: opts.warmth || 0 };
    var key = [seed, variant, o.lightOn ? 1 : 0, o.warmth > 0 ? 1 : 0].join('|');
    if (_cache.has(key)) return _cache.get(key);

    var P = PALETTES[variant] || PALETTES.living;
    var R = rng(seed * 104729 + 17);
    var far = mk(), mid = mk(), near = mk();
    var geo = drawFar(far.getContext('2d'), P, R, o);
    drawMid(mid.getContext('2d'), P, R, geo, variant, o);
    drawNear(near.getContext('2d'), P, R, geo, variant, o);

    var res = { far: far, mid: mid, near: near, variant: variant, seed: seed, horizon: geo.horizon / S };
    if (_cache.size > 12) _cache.delete(_cache.keys().next().value);
    _cache.set(key, res);
    return res;
  }

  var api = { build: build, VARIANTS: VARIANTS, SIZE: S };
  root.PhotorealInterior = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
