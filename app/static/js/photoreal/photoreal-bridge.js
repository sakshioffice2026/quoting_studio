/* app/static/js/photoreal/photoreal-bridge.js
 *
 * Connects the photoreal engine to the existing visualiser without touching
 * visualiser.html. It replaces the global _paintLifeOpening() (the "Bring it
 * to life" pass) with the WebGL pipeline. If WebGL or any module is missing,
 * or a paint fails, the original pass runs unchanged.
 *
 * Globals read from the page: _life, _lifeBase, _applyHomographyWarp,
 * DESIGNS, QS_WINDOW_ID, bgImage, drawBackground, render.
 *
 * Public API:
 *   PhotorealBridge.enable(bool)
 *   PhotorealBridge.isEnabled()
 *   PhotorealBridge.options   // { variant, lightOn, interiorBright, sill }
 *   PhotorealBridge.refresh() // re-render after changing options
 */
(function (root) {
  'use strict';

  var original = null;
  var enabled = true;
  var options = { variant: 'auto', lightOn: true, interiorBright: 0.85, sill: undefined };

  var lightCache = { key: null, val: null };
  var photoCache = { id: null, canvas: null };

  function hashStr(s) {
    var h = 2166136261 >>> 0;
    s = String(s || '');
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return (h % 9973) + 1;
  }

  function sliderVal(id, def) {
    var el = document.getElementById(id);
    return el ? (+el.value) : def;
  }

  /* clean photo for scene analysis (bgImage, or the painted placeholder house) */
  function photoFor(stats) {
    if (typeof bgImage !== 'undefined' && bgImage) return bgImage;
    if (photoCache.id === stats.id && photoCache.canvas) return photoCache.canvas;
    try {
      var W = 240;
      var H = Math.max(60, Math.round(W * houseCanvas.height / houseCanvas.width));
      var c = document.createElement('canvas');
      c.width = W; c.height = H;
      drawBackground(c.getContext('2d'), W, H);
      photoCache.id = stats.id; photoCache.canvas = c;
      return c;
    } catch (e) { return null; }
  }

  function lightingFor(stats, wall) {
    var wk = wall && wall.mid ? wall.mid.map(Math.round).join(',') : '-';
    var key = stats.id + '|' + wk;
    if (lightCache.key === key && lightCache.val) return lightCache.val;
    var L = root.PhotorealLighting.analyze({ photo: photoFor(stats), stats: stats });
    if (wall && wall.mid) {
      L.wall = [wall.mid[0] / 255, wall.mid[1] / 255, wall.mid[2] / 255];
    }
    lightCache.key = key; lightCache.val = L;
    return L;
  }

  function paintPhotoreal(ctx, cw, ch, s, op, tex, stats, wall) {
    var self = this, args = arguments;
    var r = root.PhotorealRenderer && root.PhotorealRenderer.get();
    var ready = enabled && r && r.supported && root.PhotorealLayers &&
                root.PhotorealInterior && root.PhotorealLighting;
    if (!ready) return original.apply(self, args);

    var designId = op.design_window_id || QS_WINDOW_ID;
    var design = (typeof DESIGNS !== 'undefined') ? DESIGNS[designId] : null;
    if (!design) return original.apply(self, args);

    var t = _life.t;
    _lifeBase(ctx, s, wall, t);                       // hides the old window on the photo
    if (t < 0.999) _applyHomographyWarp(ctx, cw, ch, s);   // flat sticker fades out as detail fades in

    var ok = r.paint(ctx, cw, ch, s, {
      design: design,
      lighting: lightingFor(stats, wall),
      reflect: sliderVal('reflectSlider', 50) / 100,
      yawDeg: sliderVal('yawSlider', 0),
      opacity: op.opacity != null ? op.opacity : 0.92,
      brightness: op.brightness != null ? op.brightness : 1,
      intensity: _life.intensity,
      life: t,
      glare: _life.glare,
      seed: hashStr(op.id || designId),
      variant: options.variant,
      lightOn: options.lightOn,
      interiorBright: options.interiorBright,
      sill: options.sill
    });
    if (!ok) return original.apply(self, args);
  }

  function install() {
    if (typeof root._paintLifeOpening !== 'function') {
      if (root.console) console.warn('[Photoreal] _paintLifeOpening not found; bridge not installed');
      return;
    }
    if (root._paintLifeOpening.__photoreal) return;
    original = root._paintLifeOpening;
    paintPhotoreal.__photoreal = true;
    root._paintLifeOpening = paintPhotoreal;
    if (typeof root.render === 'function') root.render();
  }

  root.PhotorealBridge = {
    enable: function (v) {
      enabled = !!v;
      if (typeof root.render === 'function') root.render();
    },
    isEnabled: function () { return enabled; },
    options: options,
    refresh: function () {
      lightCache.key = null;
      if (typeof root.render === 'function') root.render();
    }
  };

  if (document.readyState === 'complete') install();
  else root.addEventListener('load', install);
})(typeof window !== 'undefined' ? window : this);
