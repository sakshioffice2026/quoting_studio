/* Public live visualiser: renders a quoted window/door onto the customer's home photo.
   Read-only, token scoped, works without a staff login. */
(function () {
  'use strict';

  /* ---------- homography ---------- */
  function computeH(src, dst) {
    var A = [], i, j, r;
    for (i = 0; i < 4; i++) {
      var sx = src[i][0], sy = src[i][1], dx = dst[i][0], dy = dst[i][1];
      A.push([-sx, -sy, -1, 0, 0, 0, dx * sx, dx * sy, dx]);
      A.push([0, 0, 0, -sx, -sy, -1, dy * sx, dy * sy, dy]);
    }
    var M = A.map(function (row) { return row.slice(0, 8).concat([-row[8]]); });
    for (var col = 0; col < 8; col++) {
      var maxRow = col;
      for (r = col + 1; r < 8; r++) if (Math.abs(M[r][col]) > Math.abs(M[maxRow][col])) maxRow = r;
      var tmp = M[col]; M[col] = M[maxRow]; M[maxRow] = tmp;
      var pivot = M[col][col];
      if (Math.abs(pivot) < 1e-10) continue;
      for (r = 0; r < 8; r++) {
        if (r === col) continue;
        var f = M[r][col] / pivot;
        for (j = col; j <= 8; j++) M[r][j] -= f * M[col][j];
      }
    }
    var h = M.map(function (row, k) { return row[8] / row[k]; });
    h.push(1);
    return h;
  }

  /* ---------- texture from design JSON ---------- */
  function rasterDesign(d, tint) {
    d = d || {};
    var W = d.width || 1200, H = d.height || 1400;
    var s = 1400 / Math.max(W, H);
    var cw = Math.max(60, Math.round(W * s)), ch = Math.max(60, Math.round(H * s));
    var cv = document.createElement('canvas');
    cv.width = cw; cv.height = ch;
    var g = cv.getContext('2d');
    var shape = d.shape || 'rectangle';
    var isDoor = d.unitType === 'door';
    var bar = (d.frame && d.frame.thickness) || 68;
    var col = (d.frame && d.frame.color) || '#2B2F33';
    var rise = (d.archRise != null) ? d.archRise : Math.min(W * 0.25, 400);
    var panes = (d.panes && d.panes.length) ? d.panes
      : (d.cells && d.cells.length) ? d.cells
      : [{ x: 0, y: 0, w: 1, h: 1, infill: 'glass', glazingBars: [] }];

    function path(inset) {
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
    }

    var outer = path(0), inner = path(bar);
    var ring = new Path2D();
    ring.addPath(outer); ring.addPath(inner);
    g.fillStyle = col;
    g.fill(ring, 'evenodd');

    g.save();
    g.clip(inner);
    g.fillStyle = col;
    g.fillRect(0, 0, cw, ch);
    var mb = bar * 0.6, half = mb / 2, eps = 0.001;
    panes.forEach(function (p) {
      var px = p.x || 0, py = p.y || 0, pw = p.w == null ? 1 : p.w, ph = p.h == null ? 1 : p.h;
      var insL = (px <= eps) ? bar : half;
      var insT = (py <= eps) ? bar : half;
      var insR = (px + pw >= 1 - eps) ? bar : half;
      var insB = (py + ph >= 1 - eps) ? (isDoor ? 0 : bar) : half;
      var x = (px * W + insL) * s, y = (py * H + insT) * s;
      var w = (pw * W - insL - insR) * s, h = (ph * H - insT - insB) * s;
      if (w <= 0 || h <= 0) return;
      if (p.infill === 'panel') {
        g.fillStyle = col; g.fillRect(x, y, w, h);
        g.fillStyle = 'rgba(255,255,255,.10)'; g.fillRect(x, y, w, h);
        g.strokeStyle = 'rgba(0,0,0,.35)'; g.lineWidth = 2;
        g.strokeRect(x + w * 0.1, y + h * 0.06, w * 0.8, h * 0.88);
      } else {
        var gr = g.createLinearGradient(x, y, x + w, y + h);
        if (tint && tint !== '#DCEBF5') {
          gr.addColorStop(0, tint); gr.addColorStop(1, tint);
          g.globalAlpha = 0.8;
        } else {
          gr.addColorStop(0, 'rgba(170,210,225,.75)');
          gr.addColorStop(1, 'rgba(110,160,185,.75)');
        }
        g.fillStyle = gr; g.fillRect(x, y, w, h);
        g.globalAlpha = 1;
        g.fillStyle = 'rgba(255,255,255,.14)';
        g.beginPath();
        g.moveTo(x, y); g.lineTo(x + w * 0.45, y); g.lineTo(x, y + h * 0.45); g.closePath(); g.fill();
        g.strokeStyle = 'rgba(0,0,0,.25)'; g.lineWidth = 1; g.strokeRect(x, y, w, h);
      }
      (p.glazingBars || []).forEach(function (gb) {
        var t = Math.max(2, (gb.thickness || 18) * s);
        g.fillStyle = col;
        var vertical = gb.type === 'vertical' || gb.axis === 'v';
        if (vertical) g.fillRect(x + w * gb.pos - t / 2, y, t, h);
        else g.fillRect(x, y + h * gb.pos - t / 2, w, t);
      });
    });
    g.restore();

    /* frame bevel: gives the profile visible depth */
    g.save();
    g.strokeStyle = 'rgba(255,255,255,.28)'; g.lineWidth = Math.max(1.5, bar * s * 0.12);
    g.stroke(outer);
    g.strokeStyle = 'rgba(0,0,0,.45)'; g.lineWidth = Math.max(1.5, bar * s * 0.10);
    g.stroke(inner);
    g.restore();
    return cv;
  }

  /* ---------- painted fallback wall (when no home photo exists) ---------- */
  function drawPaintedHouse(ctx, w, h) {
    var sky = ctx.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, '#C8DDE6'); sky.addColorStop(.55, '#E4DCC6'); sky.addColorStop(1, '#C6B48A');
    ctx.fillStyle = sky; ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#D6CAB2'; ctx.fillRect(w * .04, h * .06, w * .92, h * .94);
    ctx.fillStyle = '#7B9B5E'; ctx.fillRect(0, h * .9, w, h * .1);
  }

  /* ---------- helpers ---------- */
  function toPts(c) {
    return { tl: c.tl, tr: c.tr, bl: c.bl, br: c.br };
  }
  function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
  function unit(a, b) { var d = dist(a, b) || 1; return { x: (b.x - a.x) / d, y: (b.y - a.y) / d }; }
  function centroid(s) {
    return { x: (s.tl.x + s.tr.x + s.bl.x + s.br.x) / 4, y: (s.tl.y + s.tr.y + s.bl.y + s.br.y) / 4 };
  }
  function quadPath(ctx, s) {
    ctx.beginPath();
    ctx.moveTo(s.tl.x, s.tl.y); ctx.lineTo(s.tr.x, s.tr.y);
    ctx.lineTo(s.br.x, s.br.y); ctx.lineTo(s.bl.x, s.bl.y);
    ctx.closePath();
  }
  function bounds(list) {
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    list.forEach(function (s) {
      ['tl', 'tr', 'bl', 'br'].forEach(function (k) {
        x0 = Math.min(x0, s[k].x); y0 = Math.min(y0, s[k].y);
        x1 = Math.max(x1, s[k].x); y1 = Math.max(y1, s[k].y);
      });
    });
    return { x0: x0, y0: y0, x1: x1, y1: y1 };
  }

  /* perspective warp of a texture into the quad (CPU, bilinear) */
  function warp(ctx, cw, ch, tex, s, opacity, brightness) {
    var sw = tex.width, sh = tex.height;
    var src = [[0, 0], [sw, 0], [0, sh], [sw, sh]];
    var dst = [[s.tl.x, s.tl.y], [s.tr.x, s.tr.y], [s.bl.x, s.bl.y], [s.br.x, s.br.y]];
    var Hinv = computeH(dst, src);
    var xs = dst.map(function (p) { return p[0]; }), ys = dst.map(function (p) { return p[1]; });
    var x0 = Math.max(0, Math.floor(Math.min.apply(null, xs)));
    var x1 = Math.min(cw, Math.ceil(Math.max.apply(null, xs)));
    var y0 = Math.max(0, Math.floor(Math.min.apply(null, ys)));
    var y1 = Math.min(ch, Math.ceil(Math.max.apply(null, ys)));
    if (x1 <= x0 || y1 <= y0) return;

    var sd = tex.getContext('2d').getImageData(0, 0, sw, sh).data;
    var bw = x1 - x0, bh = y1 - y0;
    var img = ctx.getImageData(x0, y0, bw, bh);
    var dd = img.data;
    var a = Hinv[0], b = Hinv[1], c = Hinv[2], d = Hinv[3], e = Hinv[4], f = Hinv[5],
        g = Hinv[6], h = Hinv[7], i = Hinv[8];

    for (var y = y0; y < y1; y++) {
      for (var x = x0; x < x1; x++) {
        var w = g * x + h * y + i;
        var px = (a * x + b * y + c) / w, py = (d * x + e * y + f) / w;
        if (px < 0 || px >= sw - 1 || py < 0 || py >= sh - 1) continue;
        var fx = Math.floor(px), fy = Math.floor(py);
        var dx = px - fx, dy = py - fy;
        var i00 = (fy * sw + fx) * 4, i10 = i00 + 4, i01 = i00 + sw * 4, i11 = i01 + 4;
        var w00 = (1 - dx) * (1 - dy), w10 = dx * (1 - dy), w01 = (1 - dx) * dy, w11 = dx * dy;
        var sa = (sd[i00 + 3] * w00 + sd[i10 + 3] * w10 + sd[i01 + 3] * w01 + sd[i11 + 3] * w11) / 255;
        if (sa < 0.01) continue;
        var al = sa * opacity;
        var di = ((y - y0) * bw + (x - x0)) * 4;
        for (var k = 0; k < 3; k++) {
          var sv = sd[i00 + k] * w00 + sd[i10 + k] * w10 + sd[i01 + k] * w01 + sd[i11 + k] * w11;
          dd[di + k] = Math.min(255, sv * brightness) * al + dd[di + k] * (1 - al);
        }
        dd[di + 3] = 255;
      }
    }
    ctx.putImageData(img, x0, y0);
  }

  /* ---------- depth cues ---------- */
  function contactShadow(ctx, s) {
    var w = dist(s.tl, s.tr);
    var blur = Math.max(4, w * 0.035), off = Math.max(2, w * 0.012), BIG = 100000;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.moveTo(s.tl.x, s.tl.y); ctx.lineTo(s.tr.x, s.tr.y);
    ctx.lineTo(s.br.x, s.br.y); ctx.lineTo(s.bl.x, s.bl.y); ctx.closePath();
    ctx.clip('evenodd');
    ctx.shadowColor = 'rgba(0,0,0,0.38)';
    ctx.shadowBlur = blur;
    ctx.shadowOffsetX = BIG + off; ctx.shadowOffsetY = off * 1.4;
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.moveTo(s.tl.x - BIG, s.tl.y); ctx.lineTo(s.tr.x - BIG, s.tr.y);
    ctx.lineTo(s.br.x - BIG, s.br.y); ctx.lineTo(s.bl.x - BIG, s.bl.y);
    ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  function edgeShade(ctx, p0, p1, c, depth, a) {
    var mx = (p0.x + p1.x) / 2, my = (p0.y + p1.y) / 2;
    var nx = c.x - mx, ny = c.y - my, L = Math.hypot(nx, ny) || 1;
    nx /= L; ny /= L;
    var g = ctx.createLinearGradient(mx, my, mx + nx * depth, my + ny * depth);
    g.addColorStop(0, 'rgba(0,0,0,' + a.toFixed(3) + ')');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.moveTo(p0.x, p0.y); ctx.lineTo(p1.x, p1.y);
    ctx.lineTo(p1.x + nx * depth, p1.y + ny * depth);
    ctx.lineTo(p0.x + nx * depth, p0.y + ny * depth);
    ctx.closePath(); ctx.fill();
  }

  function reveal(ctx, s) {
    var c = centroid(s), w = dist(s.tl, s.tr);
    var depth = Math.max(3, w * 0.06);
    ctx.save();
    quadPath(ctx, s); ctx.clip();
    edgeShade(ctx, s.tl, s.tr, c, depth, 0.42);
    edgeShade(ctx, s.tl, s.bl, c, depth, 0.32);
    edgeShade(ctx, s.tr, s.br, c, depth * 0.5, 0.12);
    edgeShade(ctx, s.bl, s.br, c, depth * 0.4, 0.10);
    ctx.restore();
  }

  function sill(ctx, s) {
    var w = dist(s.bl, s.br);
    if (w < 24) return;
    var dirX = unit(s.bl, s.br);
    var down = unit({ x: (s.tl.x + s.tr.x) / 2, y: (s.tl.y + s.tr.y) / 2 },
                    { x: (s.bl.x + s.br.x) / 2, y: (s.bl.y + s.br.y) / 2 });
    var th = w * 0.04, over = w * 0.03;
    var A = { x: s.bl.x - dirX.x * over, y: s.bl.y - dirX.y * over };
    var B = { x: s.br.x + dirX.x * over, y: s.br.y + dirX.y * over };
    var C = { x: B.x + down.x * th, y: B.y + down.y * th };
    var D = { x: A.x + down.x * th, y: A.y + down.y * th };
    var sh = th * 1.9;
    var E = { x: C.x + down.x * sh, y: C.y + down.y * sh };
    var F = { x: D.x + down.x * sh, y: D.y + down.y * sh };
    ctx.save();
    var sg = ctx.createLinearGradient(D.x, D.y, F.x, F.y);
    sg.addColorStop(0, 'rgba(0,0,0,0.30)'); sg.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = sg;
    ctx.beginPath(); ctx.moveTo(D.x, D.y); ctx.lineTo(C.x, C.y); ctx.lineTo(E.x, E.y); ctx.lineTo(F.x, F.y);
    ctx.closePath(); ctx.fill();
    var fg = ctx.createLinearGradient(A.x, A.y, D.x, D.y);
    fg.addColorStop(0, '#d9d4c8'); fg.addColorStop(1, '#aaa598');
    ctx.fillStyle = fg;
    ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.lineTo(C.x, C.y); ctx.lineTo(D.x, D.y);
    ctx.closePath(); ctx.fill();
    ctx.strokeStyle = 'rgba(255,255,255,.4)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(A.x, A.y); ctx.lineTo(B.x, B.y); ctx.stroke();
    ctx.restore();
  }

  function glare(ctx, s) {
    ctx.save();
    quadPath(ctx, s); ctx.clip();
    var g = ctx.createLinearGradient(s.tl.x, s.tl.y, s.br.x, s.br.y);
    g.addColorStop(0, 'rgba(255,255,255,0.20)');
    g.addColorStop(0.35, 'rgba(255,255,255,0.0)');
    g.addColorStop(1, 'rgba(255,255,255,0.0)');
    ctx.fillStyle = g;
    ctx.fillRect(Math.min(s.tl.x, s.bl.x), Math.min(s.tl.y, s.tr.y),
      Math.max(s.tr.x, s.br.x) - Math.min(s.tl.x, s.bl.x),
      Math.max(s.bl.y, s.br.y) - Math.min(s.tl.y, s.tr.y));
    ctx.restore();
  }

  /* ---------- component ---------- */
  function PublicVisualiser(root) {
    this.root = root;
    this.canvas = root.querySelector('canvas');
    this.status = root.querySelector('[data-pv-status]');
    this.ctx = this.canvas.getContext('2d');
    this.state = { before: false, depth: true, full: false };
    this.data = null;
    this.photo = null;
    this.textures = {};
    this._bind();
    this._load();
  }

  PublicVisualiser.prototype._bind = function () {
    var self = this;
    var btns = this.root.querySelectorAll('[data-pv]');
    Array.prototype.forEach.call(btns, function (btn) {
      btn.addEventListener('click', function () {
        var k = btn.getAttribute('data-pv');
        if (k === 'before') self.state.before = true;
        if (k === 'after') self.state.before = false;
        if (k === 'depth') self.state.depth = !self.state.depth;
        if (k === 'view') self.state.full = !self.state.full;
        self._syncButtons();
        self.render();
      });
    });
    var t;
    window.addEventListener('resize', function () {
      clearTimeout(t); t = setTimeout(function () { self.render(); }, 150);
    });
    this._syncButtons();
  };

  PublicVisualiser.prototype._syncButtons = function () {
    var st = this.state;
    Array.prototype.forEach.call(this.root.querySelectorAll('[data-pv]'), function (btn) {
      var k = btn.getAttribute('data-pv'), on = false;
      if (k === 'before') on = st.before;
      if (k === 'after') on = !st.before;
      if (k === 'depth') on = st.depth;
      if (k === 'view') on = st.full;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.classList.toggle('on', on);
      if (k === 'view') btn.textContent = st.full ? 'Close-up' : 'Full house';
    });
  };

  PublicVisualiser.prototype._setStatus = function (msg) {
    if (this.status) this.status.textContent = msg || '';
  };

  PublicVisualiser.prototype._load = function () {
    var self = this;
    this._setStatus('Loading preview…');
    fetch(this.root.getAttribute('data-pv-url'), { headers: { Accept: 'application/json' }, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(function (data) {
        self.data = data;
        var keys = Object.keys(data.designs || {});
        keys.forEach(function (k) { self.textures[k] = null; });
        if (!data.photo) return null;
        return new Promise(function (resolve) {
          var img = new Image();
          img.onload = function () { self.photo = img; resolve(); };
          img.onerror = function () { resolve(); };
          img.src = data.photo;
        });
      })
      .then(function () {
        self._setStatus('');
        self.root.classList.add('ready');
        self.render();
      })
      .catch(function () {
        self._setStatus('Live preview unavailable');
        self.root.classList.add('failed');
      });
  };

  PublicVisualiser.prototype._tex = function (wid, tint) {
    var key = wid + '|' + (tint || '');
    if (!this._cache) this._cache = {};
    if (!this._cache[key]) {
      var d = this.data.designs[String(wid)];
      if (!d) return null;
      this._cache[key] = rasterDesign(d, tint);
    }
    return this._cache[key];
  };

  /* Resolve the list of quads (in photo space) and the visible crop. */
  PublicVisualiser.prototype._scene = function () {
    var data = this.data, photo = this.photo, openings = [];
    var pw, ph;

    if (photo) {
      pw = photo.naturalWidth || photo.width;
      ph = photo.naturalHeight || photo.height;
      openings = (data.openings || []).map(function (o) {
        return { window_id: o.window_id, mine: o.mine, opacity: o.opacity, brightness: o.brightness,
                 tint: o.tint, quad: toPts(o.corners) };
      });
    } else {
      /* no home photo: place the unit on a painted wall */
      pw = 1400; ph = 1000;
      var wid = String(data.window_id || 0);
      var d = data.designs[wid] || data.designs['0'];
      if (d) {
        var ratio = (d.width || 1200) / (d.height || 1400);
        var hh = ph * 0.55, ww = hh * ratio;
        if (ww > pw * 0.6) { ww = pw * 0.6; hh = ww / ratio; }
        var cx = pw / 2, cy = ph * 0.46;
        openings = [{ window_id: data.window_id || 0, mine: true, opacity: 1, brightness: 1, tint: null,
          quad: { tl: { x: cx - ww / 2, y: cy - hh / 2 }, tr: { x: cx + ww / 2, y: cy - hh / 2 },
                  bl: { x: cx - ww / 2, y: cy + hh / 2 }, br: { x: cx + ww / 2, y: cy + hh / 2 } } }];
      }
    }

    var focus = openings.filter(function (o) { return o.mine; });
    var target = (focus.length ? focus : openings).map(function (o) { return o.quad; });
    var crop = { x: 0, y: 0, w: pw, h: ph };
    if (!this.state.full && target.length) {
      var b = bounds(target);
      var bw = b.x1 - b.x0, bh = b.y1 - b.y0;
      var pad = Math.max(bw, bh) * 0.9 + 40;
      var cw = Math.min(pw, Math.max(bw + pad * 2, (bh + pad * 2) * 1.5));
      var chh = Math.min(ph, cw / 1.5);
      if (chh < bh + pad) { chh = Math.min(ph, bh + pad); cw = Math.min(pw, chh * 1.5); }
      var cxm = (b.x0 + b.x1) / 2, cym = (b.y0 + b.y1) / 2;
      crop.w = cw; crop.h = chh;
      crop.x = Math.max(0, Math.min(pw - cw, cxm - cw / 2));
      crop.y = Math.max(0, Math.min(ph - chh, cym - chh / 2));
    }
    return { pw: pw, ph: ph, crop: crop, openings: openings };
  };

  PublicVisualiser.prototype.render = function () {
    if (!this.data) return;
    var sc = this._scene();
    var box = this.canvas.parentElement;
    var cssW = Math.max(240, box.clientWidth || 640);
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var outW = Math.round(cssW * dpr);
    var k = outW / sc.crop.w;
    var outH = Math.round(sc.crop.h * k);

    this.canvas.width = outW; this.canvas.height = outH;
    this.canvas.style.width = '100%';
    this.canvas.style.aspectRatio = outW + ' / ' + outH;

    var ctx = this.ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, outW, outH);

    if (this.photo) {
      ctx.drawImage(this.photo, sc.crop.x, sc.crop.y, sc.crop.w, sc.crop.h, 0, 0, outW, outH);
    } else {
      var tmp = document.createElement('canvas');
      tmp.width = sc.pw; tmp.height = sc.ph;
      drawPaintedHouse(tmp.getContext('2d'), sc.pw, sc.ph);
      ctx.drawImage(tmp, sc.crop.x, sc.crop.y, sc.crop.w, sc.crop.h, 0, 0, outW, outH);
    }

    if (this.state.before) return;

    var self = this, depth = this.state.depth;
    function map(p) { return { x: (p.x - sc.crop.x) * k, y: (p.y - sc.crop.y) * k }; }

    /* other openings first, this item's opening last (on top) */
    var ordered = sc.openings.filter(function (o) { return !o.mine; })
      .concat(sc.openings.filter(function (o) { return o.mine; }));

    ordered.forEach(function (o) {
      var tex = self._tex(o.window_id, o.tint);
      if (!tex) return;
      var q = o.quad;
      var s = { tl: map(q.tl), tr: map(q.tr), bl: map(q.bl), br: map(q.br) };
      if (depth) contactShadow(ctx, s);
      warp(ctx, outW, outH, tex, s, o.opacity == null ? 0.92 : o.opacity, o.brightness == null ? 1 : o.brightness);
      if (depth) { reveal(ctx, s); sill(ctx, s); glare(ctx, s); }
    });
  };

  function init() {
    var nodes = document.querySelectorAll('[data-pv-url]');
    Array.prototype.forEach.call(nodes, function (n) {
      if (n.__pv) return;
      n.__pv = new PublicVisualiser(n);
    });
  }

  window.PublicVisualiser = PublicVisualiser;
  window.PublicVisualiserInit = init;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
