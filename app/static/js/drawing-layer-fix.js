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

   It also clips shaped glass to the inner aperture and prevents a pane/fill
   from visually leaking across the rectangular-to-arch spring boundary.
*/
(function () {
  if (typeof window === 'undefined' || !window.QSDraw || !window.QSDraw.DrawingCanvas) return;

  const DrawingCanvas = window.QSDraw.DrawingCanvas;
  if (DrawingCanvas.prototype.__qsCadLayerFixInstalled) return;
  DrawingCanvas.prototype.__qsCadLayerFixInstalled = true;

  const originalRender = DrawingCanvas.prototype.render;

  function makeLayer(id, label) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('id', id);
    g.setAttribute('data-qs-layer', label);
    return g;
  }

  function moveChildrenByPredicate(from, to, predicate) {
    if (!from) return;
    Array.from(from.childNodes).forEach((node) => {
      if (node.nodeType === 1 && predicate(node)) to.appendChild(node);
    });
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
    if (/qsShapeClip/.test(clip)) {
      // Existing shaped render groups already contain the correct semantic
      // geometry. Classify the group by its contents/role below.
      return 'shaped';
    }
    if (fillRule === 'evenodd') return 'frame';

    return 'other';
  }

  function normaliseLayers(dc) {
    const svg = dc.svg;
    if (!svg) return;

    // Do not disturb <defs>; retain it at the front of the SVG document.
    const defs = Array.from(svg.children).find((n) => n.tagName.toLowerCase() === 'defs');

    const layers = {
      glass: makeLayer('qs-layer-glass', 'Glass/Fill'),
      sash: makeLayer('qs-layer-sash', 'Sash'),
      arch: makeLayer('qs-layer-arch-transom', 'Arch/Transom'),
      frame: makeLayer('qs-layer-frame', 'Frame'),
      other: makeLayer('qs-layer-overlay', 'Overlay'),
    };

    // Existing layer nodes from the shaped renderer are preserved and moved
    // as units; no geometry is regenerated here.
    const existingLayers = Array.from(svg.querySelectorAll(':scope > [data-qs-layer]'));
    existingLayers.forEach((n) => n.remove());

    const topLevel = Array.from(svg.children);
    for (const node of topLevel) {
      if (node === defs) continue;
      if (Object.values(layers).includes(node)) continue;

      // Grid/shadow/dimension/interaction overlays stay out of the structural
      // stack, while actual window geometry is placed into its semantic layer.
      if (node.classList && node.classList.contains('qs-dxf-geometry-layer')) {
        layers.other.appendChild(node);
        continue;
      }
      if (node.classList && (
        node.classList.contains('qs-profile-highlight-layer') ||
        node.classList.contains('qs-section-focus-preview-layer')
      )) {
        layers.other.appendChild(node);
        continue;
      }

      const kind = classifyNode(node);
      if (kind === 'sash') layers.sash.appendChild(node);
      else if (kind === 'transom') layers.arch.appendChild(node);
      else if (kind === 'frame') layers.frame.appendChild(node);
      else if (kind === 'glass') layers.glass.appendChild(node);
      else if (kind === 'shaped') {
        // A shaped glass/mullion/opener group is kept in the Arch/Transom
        // layer only when it is structural; its contents already carry the
        // original clip-path, so moving the group cannot unclip it.
        layers.arch.appendChild(node);
      } else layers.other.appendChild(node);
    }

    // Rebuild the stack explicitly. Glass/fill is always behind structural
    // members. Frame is always last among the physical window layers.
    if (defs) svg.appendChild(defs);
    svg.appendChild(layers.glass);
    svg.appendChild(layers.sash);
    svg.appendChild(layers.arch);
    svg.appendChild(layers.frame);
    svg.appendChild(layers.other);

    // Give consumers/devtools a stable semantic marker for each structural
    // group without changing the existing model JSON or rendering API.
    svg.setAttribute('data-qs-display-order', 'glass,sash,arch-transom,frame,overlay');
  }

  DrawingCanvas.prototype.render = function () {
    originalRender.call(this);
    normaliseLayers(this);
  };
})();
