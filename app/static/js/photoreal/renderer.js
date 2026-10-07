/* app/static/js/photoreal/renderer.js
 *
 * WebGL1 renderer for the photoreal window pass.
 *
 *   const r = PhotorealRenderer.get();
 *   if (r.supported) {
 *     r.paintTiled(ctx2d, cw, ch, quad, {
 *       design, lighting, reflect, opacity, brightness, intensity,
 *       life, glare, yawDeg, seed, variant, lightOn, sill, interiorBright
 *     });
 *   }
 *
 * quad = { tl:{x,y}, tr:{x,y}, bl:{x,y}, br:{x,y} } in canvas pixel space.
 *
 * Only the bounding box of the window (+ reveal / shadow / sill margin) is
 * drawn back to the 2D canvas, with alpha. Nothing else on the photo changes.
 *
 * The WebGL canvas is capped to a tile (never larger than the GPU limits), and
 * the window region is rendered tile by tile. Export at native photo size
 * therefore never falls back because a drawing buffer was too small.
 * paint() is kept as an alias of paintTiled().
 */
(function (root) {
  'use strict';

  var TEX_LIMIT = 40;
  var TILE_CAP = 2048;
  var TILE_MIN = 256;
  var LAYER_MAX = 2048;
  var REGION_MAX_PX = 120000000;

  function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }

  /* ---------- homography (4 point DLT, h22 = 1) ---------- */
  function solveHomography(src, dst) {
    var M = [], i, j, r, c;
    for (i = 0; i < 4; i++) {
      var sx = src[i][0], sy = src[i][1], dx = dst[i][0], dy = dst[i][1];
      M.push([sx, sy, 1, 0, 0, 0, -dx * sx, -dx * sy, dx]);
      M.push([0, 0, 0, sx, sy, 1, -dy * sx, -dy * sy, dy]);
    }
    for (c = 0; c < 8; c++) {
      var piv = c;
      for (r = c + 1; r < 8; r++) if (Math.abs(M[r][c]) > Math.abs(M[piv][c])) piv = r;
      var tmp = M[c]; M[c] = M[piv]; M[piv] = tmp;
      var p = M[c][c];
      if (Math.abs(p) < 1e-12) return null;
      for (j = c; j < 9; j++) M[c][j] /= p;
      for (r = 0; r < 8; r++) {
        if (r === c) continue;
        var f = M[r][c];
        if (f === 0) continue;
        for (j = c; j < 9; j++) M[r][j] -= f * M[c][j];
      }
    }
    var h = [];
    for (i = 0; i < 8; i++) h.push(M[i][8]);
    h.push(1);
    return h;
  }

  function Renderer() {
    var self = this;
    this.canvas = document.createElement('canvas');
    this.gl = null;
    this.prog = null;
    this.loc = {};
    this.texCache = new Map();
    this.supported = false;
    this.lost = false;
    this.lastError = null;
    this.lastFailure = null;
    this.maxTile = TILE_CAP;
    this._init();
    this.canvas.addEventListener('webglcontextlost', function (e) {
      e.preventDefault();
      self.lost = true;
      self.supported = false;
    });
    this.canvas.addEventListener('webglcontextrestored', function () {
      self.lost = false;
      self.texCache.clear();
      self._init();
    });
  }

  Renderer.prototype._compile = function (type, src) {
    var gl = this.gl;
    var sh = gl.createShader(type);
    gl.shaderSource(sh, src);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(sh) || 'shader compile failed');
    }
    return sh;
  };

  Renderer.prototype._init = function () {
    try {
      var gl = this.canvas.getContext('webgl', {
        alpha: true, premultipliedAlpha: true, antialias: false,
        depth: false, stencil: false, preserveDrawingBuffer: false
      }) || this.canvas.getContext('experimental-webgl');
      if (!gl) throw new Error('WebGL unavailable');
      if (!root.PhotorealShaders) throw new Error('PhotorealShaders not loaded');
      this.gl = gl;

      var prog = gl.createProgram();
      gl.attachShader(prog, this._compile(gl.VERTEX_SHADER, root.PhotorealShaders.VERT));
      gl.attachShader(prog, this._compile(gl.FRAGMENT_SHADER, root.PhotorealShaders.FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(prog) || 'program link failed');
      }
      gl.useProgram(prog);
      this.prog = prog;

      var buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
      var aPos = gl.getAttribLocation(prog, 'aPos');
      gl.enableVertexAttribArray(aPos);
      gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

      this.loc = {};
      var names = root.PhotorealShaders.UNIFORMS;
      for (var i = 0; i < names.length; i++) {
        this.loc[names[i]] = gl.getUniformLocation(prog, names[i]);
      }
      gl.disable(gl.BLEND);
      gl.disable(gl.DEPTH_TEST);
      gl.disable(gl.SCISSOR_TEST);

      /* tile size limited by what this GPU can actually hold */
      var lim = TILE_CAP;
      try {
        var mt = gl.getParameter(gl.MAX_TEXTURE_SIZE) || TILE_CAP;
        var mr = gl.getParameter(gl.MAX_RENDERBUFFER_SIZE) || TILE_CAP;
        var mv = gl.getParameter(gl.MAX_VIEWPORT_DIMS);
        lim = Math.min(lim, mt, mr);
        if (mv && mv.length) lim = Math.min(lim, mv[0], mv[1]);
      } catch (e2) { lim = 1024; }
      this.maxTile = Math.max(TILE_MIN, lim);

      this.supported = true;
      this.lastError = null;
    } catch (e) {
      this.supported = false;
      this.lastError = e;
      if (root.console) console.warn('[Photoreal] WebGL init failed:', e);
    }
  };

  /* ---------- textures ---------- */
  Renderer.prototype._texture = function (canvas) {
    var gl = this.gl;
    var tex = this.texCache.get(canvas);
    if (tex) {
      this.texCache.delete(canvas);
      this.texCache.set(canvas, tex);
      return tex;
    }
    tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, canvas);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    this.texCache.set(canvas, tex);
    if (this.texCache.size > TEX_LIMIT) {
      var oldKey = this.texCache.keys().next().value;
      gl.deleteTexture(this.texCache.get(oldKey));
      this.texCache.delete(oldKey);
    }
    return tex;
  };

  Renderer.prototype._bind = function (unit, name, canvas) {
    var gl = this.gl;
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, this._texture(canvas));
    if (this.loc[name]) gl.uniform1i(this.loc[name], unit);
  };

  Renderer.prototype._set = function (name, v) {
    var gl = this.gl, l = this.loc[name];
    if (!l) return;
    if (typeof v === 'number') { gl.uniform1f(l, v); return; }
    if (v && v.length === 2) { gl.uniform2fv(l, v); return; }
    if (v && (v.length === 3 || v.length === 18)) { gl.uniform3fv(l, v); return; }
  };

  /* ---------- view vector from the quad's foreshortening ---------- */
  function viewFromQuad(q, yawDeg) {
    var hL = Math.hypot(q.bl.x - q.tl.x, q.bl.y - q.tl.y);
    var hR = Math.hypot(q.br.x - q.tr.x, q.br.y - q.tr.y);
    var wT = Math.hypot(q.tr.x - q.tl.x, q.tr.y - q.tl.y);
    var wB = Math.hypot(q.br.x - q.bl.x, q.br.y - q.bl.y);
    var yaw = clamp((hR - hL) / ((hR + hL) || 1) * 1.5, -0.6, 0.6);
    var pitch = clamp((wB - wT) / ((wB + wT) || 1) * 1.5, -0.6, 0.6);
    yaw += Math.tan((yawDeg || 0) * Math.PI / 180) * 0.6;
    var l = Math.hypot(yaw, pitch, 1) || 1;
    return new Float32Array([yaw / l, pitch / l, 1 / l]);
  }

  Renderer.prototype._fail = function (reason, err) {
    this.lastFailure = reason;
    if (err) this.lastError = err;
    if (root.console) console.warn('[Photoreal] paint skipped: ' + reason, err || '');
    return false;
  };

  /* ---------- paint one opening, in capped tiles ---------- */
  Renderer.prototype.paintTiled = function (ctx, cw, ch, quad, o) {
    if (!this.supported || this.lost) return this._fail('renderer unavailable');
    o = o || {};
    var gl = this.gl;
    var PL = root.PhotorealLayers, PI = root.PhotorealInterior, PG = root.PhotorealLighting;
    if (!PL || !PI || !PG || !o.lighting) return this._fail('engine modules or lighting missing');

    try {
      var xs = [quad.tl.x, quad.tr.x, quad.bl.x, quad.br.x];
      var ys = [quad.tl.y, quad.tr.y, quad.bl.y, quad.br.y];
      var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
      var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
      var qw = maxX - minX, qh = maxY - minY;
      if (qw < 8 || qh < 8) return this._fail('opening too small');

      var mx = qw * 0.46, my = qh * 0.46;
      var bx = Math.max(0, Math.floor(minX - mx)), by = Math.max(0, Math.floor(minY - my));
      var bx2 = Math.min(cw, Math.ceil(maxX + mx)), by2 = Math.min(ch, Math.ceil(maxY + my));
      var bw = bx2 - bx, bh = by2 - by;
      if (bw < 2 || bh < 2) return this._fail('opening outside canvas');
      if (bw * bh > REGION_MAX_PX) return this._fail('region too large');

      /* tile size: GPU limit, then whatever the drawing buffer really gives */
      var T = Math.min(this.maxTile, TILE_CAP);
      var tw0 = Math.min(bw, T), th0 = Math.min(bh, T);
      var tries = 0;
      while (tries < 4) {
        if (this.canvas.width !== tw0 || this.canvas.height !== th0) {
          this.canvas.width = tw0; this.canvas.height = th0;
        }
        if (gl.drawingBufferWidth >= tw0 && gl.drawingBufferHeight >= th0) break;
        tw0 = Math.max(TILE_MIN / 2, Math.min(tw0, gl.drawingBufferWidth) >> 1 << 1);
        th0 = Math.max(TILE_MIN / 2, Math.min(th0, gl.drawingBufferHeight) >> 1 << 1);
        tries++;
      }
      if (gl.drawingBufferWidth < tw0 || gl.drawingBufferHeight < th0) {
        return this._fail('drawing buffer too small');
      }

      /* layers sized to the on-screen window (limits minification aliasing) */
      var need = Math.max(qw, qh) * 1.5;
      var maxSize = clamp(Math.ceil(need / 128) * 128, 256, LAYER_MAX);
      var design = o.design || {};
      var layers = PL.build(design, { maxSize: maxSize });
      var interior = PI.build({
        seed: o.seed != null ? o.seed : 1,
        variant: o.variant || 'auto',
        lightOn: o.lightOn !== false,
        warmth: o.lighting.warmth
      });

      var lw = layers.width, lh = layers.height;
      var Hm = solveHomography(
        [[quad.tl.x, quad.tl.y], [quad.tr.x, quad.tr.y], [quad.bl.x, quad.bl.y], [quad.br.x, quad.br.y]],
        [[0, 0], [lw, 0], [0, lh], [lw, lh]]
      );
      if (!Hm) return this._fail('degenerate quad');

      gl.useProgram(this.prog);
      gl.viewport(0, 0, tw0, th0);
      gl.disable(gl.SCISSOR_TEST);
      gl.clearColor(0, 0, 0, 0);

      this._bind(0, 'uLayer', layers.layerCanvas);
      this._bind(1, 'uHeight', layers.heightCanvas);
      this._bind(2, 'uMask', layers.maskCanvas);
      this._bind(3, 'uFar', interior.far);
      this._bind(4, 'uMid', interior.mid);
      this._bind(5, 'uNear', interior.near);

      var D = root.PhotorealShaders.DEFAULTS;
      var barW = layers.metrics.barPx / lh;
      var isDoor = !!layers.metrics.isDoor;

      this._set('uSrc', new Float32Array([lw, lh]));
      this._set('uCanvasH', th0);
      this._set('uTexel', new Float32Array([1 / lw, 1 / lh]));
      this._set('uAspect', lw / lh);
      this._set('uBarW', barW);

      this._set('uRelief', D.relief);
      this._set('uDepthScale', D.depthScale);
      this._set('uWallH', D.wallH);
      this._set('uAORad', clamp(barW * 0.3, 0.006, 0.02));
      this._set('uAOStrength', D.aoStrength);
      this._set('uRevealW', D.revealW);
      var hasCill = !!layers.metrics.hasCill;
      var sill = (o.sill != null) ? !!o.sill : hasCill;
      this._set('uHasSill', sill && !isDoor ? 1 : 0);
      this._set('uSillSize', D.sillSize);

      this._set('uFrameCol', new Float32Array(layers.colors.frame));
      this._set('uSashCol', new Float32Array(layers.colors.sash));
      this._set('uView', viewFromQuad(quad, o.yawDeg));
      this._set('uReflect', o.reflect != null ? o.reflect : 0.5);
      this._set('uOpacity', o.opacity != null ? o.opacity : 1);
      this._set('uBright', o.brightness != null ? o.brightness : 1);
      this._set('uIntensity', o.intensity != null ? o.intensity : 0.7);
      this._set('uLife', o.life != null ? o.life : 1);
      this._set('uGlare', o.glare != null ? o.glare : -1);
      this._set('uInteriorBright', o.interiorBright != null ? o.interiorBright : D.interiorBright);

      var U = PG.toUniforms(o.lighting);
      for (var k in U) {
        if (Object.prototype.hasOwnProperty.call(U, k)) this._set(k, U[k]);
      }

      /* tiles: shift the homography so tile pixel (0,0) = house pixel (tx,ty) */
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      for (var ty = by; ty < by2; ty += th0) {
        var th = Math.min(th0, by2 - ty);
        for (var tx = bx; tx < bx2; tx += tw0) {
          var tw = Math.min(tw0, bx2 - tx);
          var h2 = Hm[0] * tx + Hm[1] * ty + Hm[2];
          var h5 = Hm[3] * tx + Hm[4] * ty + Hm[5];
          var h8 = Hm[6] * tx + Hm[7] * ty + Hm[8];
          gl.uniformMatrix3fv(this.loc.uH, false, new Float32Array([
            Hm[0], Hm[3], Hm[6], Hm[1], Hm[4], Hm[7], h2, h5, h8
          ]));
          gl.clear(gl.COLOR_BUFFER_BIT);
          gl.drawArrays(gl.TRIANGLES, 0, 3);
          ctx.drawImage(this.canvas, 0, 0, tw, th, tx, ty, tw, th);
        }
      }
      ctx.restore();

      this.lastFailure = null;
      return true;
    } catch (e) {
      return this._fail('exception', e);
    }
  };

  /* kept for existing callers */
  Renderer.prototype.paint = function (ctx, cw, ch, quad, o) {
    return this.paintTiled(ctx, cw, ch, quad, o);
  };

  Renderer.prototype.dispose = function () {
    var gl = this.gl;
    if (gl) {
      this.texCache.forEach(function (t) { gl.deleteTexture(t); });
      if (this.prog) gl.deleteProgram(this.prog);
    }
    this.texCache.clear();
    this.supported = false;
  };

  var _inst = null;
  var api = {
    get: function () { if (!_inst) _inst = new Renderer(); return _inst; },
    Renderer: Renderer,
    solveHomography: solveHomography
  };
  root.PhotorealRenderer = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : this);
