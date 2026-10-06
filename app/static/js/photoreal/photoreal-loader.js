/* app/static/js/photoreal/photoreal-loader.js
 *
 * One script tag loads the whole photoreal engine, in order, then installs
 * the bridge. Place it at the END of visualiser.html (after the page's own
 * inline script), e.g. inside the scripts block:
 *
 *   <script src="{{ url_for('static', filename='js/photoreal/photoreal-loader.js') }}"></script>
 *
 * Load order:
 *   layer-map.js -> scene-lighting.js -> interior-gen.js -> shaders.js
 *   -> renderer.js -> photoreal-bridge.js
 *
 * If any module fails to load, the bridge is not installed and the original
 * "Bring it to life" pass keeps working.
 */
(function () {
  'use strict';

  var MODULES = [
    'layer-map.js',
    'scene-lighting.js',
    'interior-gen.js',
    'shaders.js',
    'renderer.js',
    'photoreal-bridge.js'
  ];

  var cur = document.currentScript;
  var src = cur && cur.src ? cur.src : '';
  var base = src ? src.slice(0, src.lastIndexOf('/') + 1) : '/static/js/photoreal/';
  var query = src.indexOf('?') > -1 ? src.slice(src.indexOf('?')) : '';

  function load(i) {
    if (i >= MODULES.length) return;
    var s = document.createElement('script');
    s.src = base + MODULES[i] + query;
    s.async = false;
    s.onload = function () { load(i + 1); };
    s.onerror = function () {
      if (window.console) console.warn('[Photoreal] failed to load ' + MODULES[i] + '; engine disabled');
    };
    document.head.appendChild(s);
  }

  load(0);
})();
