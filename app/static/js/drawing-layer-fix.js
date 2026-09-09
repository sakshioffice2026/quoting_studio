/*
   QUOTING STUDIO — CAD DRAW ORDER / LAYER NORMALISATION
   -----------------------------------------------------
   Keeps the existing drawing geometry and render logic intact. This small
   compatibility layer only classifies the SVG output after DrawingCanvas.render()
   and enforces the intended display order:

     1. Glass / Fill (back)
     2. Sash
     3. Arch / Transom
     4. Frame / boundary geometry (front)
     5. Overlay / interaction geometry

   No model geometry is regenerated here. Existing clip-paths and SVG geometry
   are retained while their display order is normalised.
*/
(function () {
  if (typeof window === 'undefined') return;

  // drawing-engine.js is a classic script, so DrawingCanvas may be exposed as
  // a global lexical binding rather than window.QSDraw. Support both forms
  // without changing the existing renderer/export pattern.
  let DrawingCanvas = null;
  if (window.QSDraw && window.QSDraw.DrawingCanvas) {
    DrawingCanvas = window.QSDraw.DrawingCanvas;
  } else if (typeof window.DrawingCanvas === 'function') {
    DrawingCanvas = window.DrawingCanvas;
  } else if (typeof DrawingCanvas === 'function') {
    DrawingCanvas = DrawingCanvas;
  }

  if (!DrawingCanvas || !DrawingCanvas.prototype ||
      typeof DrawingCanvas.prototype.render !== 'function') return;
  if (DrawingCanvas.prototype.__qsCadLayerFixInstalled) return;
  DrawingCanvas.prototype.__qsCadLayerFixInstalled = true;

  const originalRender = DrawingCanvas.prototype.render;

  function makeLayer(id, label) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('id', id);
    g.setAttribute('data-qs-layer', label);
    return g;
  }

  function classifyNode(node) {
    if (!node || node.nodeType !== 1) return 'other';

    const part = node.getAttribute('data-qs-clickable-part');
    if (part === 'sash') return 'sash';
    if (part === 'transom' || part === 'coupler') return 'transom';
    if (part === 'mullion') return 'frame';
    if (part === 'head' || part === 'cill' || part === 'jamb' || part === 'outer_frame') return 'frame';

    if (node.classList && node.classList.contains('qs-frame-bar')) return 'frame';
    if (node.classList && node.classList.contains('qs-section-focus-preview')) return 'other';
    if (node.getAttribute('data-qs-part')) return 'frame';

    const fill = node.getAttribute('fill') || '';
    const clip = node.getAttribute('clip-path') || '';
    const fillRule = node.getAttribute('fill-rule') || '';

    if (/qsGlassSky|qsObscure|qsGlassShade/.test(fill)) return 'glass';
    if (/qsShapeClip/.test(clip)) return 'arch';
    if (fillRule === 'evenodd') return 'frame';

    return 'other';
  }

  function normaliseLayers(dc) {
    const svg = dc && dc.svg;
    if (!svg) return;

    const defs = Array.from(svg.children).find(
      (n) => n.tagName && n.tagName.toLowerCase() === 'defs'
    );

    const layers = {
      glass: makeLayer('qs-layer-glass', 'Glass/Fill'),
      sash: makeLayer('qs-layer-sash', 'Sash'),
      arch: makeLayer('qs-layer-arch-transom', 'Arch/Transom'),
      frame: makeLayer('qs-layer-frame', 'Frame'),
      other: makeLayer('qs-layer-overlay', 'Overlay')
    };

    // Remove only a previous normalisation pass. Never remove or recreate
    // the renderer's actual geometry.
    Array.from(svg.children)
      .filter((n) => n.getAttribute && n.getAttribute('data-qs-layer'))
      .forEach((n) => n.remove());

    const topLevel = Array.from(svg.children);
    for (const node of topLevel) {
      if (node === defs) continue;
      const kind = classifyNode(node);

      if (node.classList && (
        node.classList.contains('qs-dxf-geometry-layer') ||
        node.classList.contains('qs-profile-highlight-layer') ||
        node.classList.contains('qs-section-focus-preview-layer')
      )) {
        layers.other.appendChild(node);
        continue;
      }

      if (kind === 'glass') layers.glass.appendChild(node);
      else if (kind === 'sash') layers.sash.appendChild(node);
      else if (kind === 'arch') layers.arch.appendChild(node);
      else if (kind === 'frame') layers.frame.appendChild(node);
      else layers.other.appendChild(node);
    }

    if (defs) svg.appendChild(defs);
    svg.appendChild(layers.glass);
    svg.appendChild(layers.sash);
    svg.appendChild(layers.arch);
    svg.appendChild(layers.frame);
    svg.appendChild(layers.other);
    svg.setAttribute('data-qs-display-order', 'glass,sash,arch-transom,frame,overlay');
  }

  DrawingCanvas.prototype.render = function () {
    originalRender.apply(this, arguments);
    normaliseLayers(this);
  };
})();
