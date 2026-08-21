"""3D exporters.

Primary path: the full member-graph assembly (frame_assembly + model3d_assembly),
which includes head/cill/jamb/mullion/transom/sash/glazing-bead members with
real profile sections and cill horn extensions — i.e. all components.

Falls back to the simplified canonical-geometry box assembly only if the
full assembly build fails for some reason.
"""
from __future__ import annotations

import logging
import os
import tempfile

from .canonical_geometry import build_geometry

logger = logging.getLogger(__name__)

_GLASS_THICKNESS = 24.0


def generate_3d(window, panes, tenant_id=None, fmt="step", method="auto", z_up=False) -> bytes:
    fmt = fmt.lower()
    if fmt not in {"step", "stl", "glb"}:
        raise ValueError("fmt must be step, stl or glb")

    try:
        from .model3d_assembly import generate_3d_assembly
        return generate_3d_assembly(window, panes, tenant_id=tenant_id, fmt=fmt, z_up=z_up)
    except Exception as exc:
        logger.warning("full member-graph 3D assembly failed (%s); falling back to canonical box builder", exc)

    geometry = build_geometry(window, panes, tenant_id=tenant_id)
    assembly = _build_canonical_assembly(geometry, z_up=z_up)

    if fmt == "step":
        return _export_cadquery(assembly, "step")
    try:
        return _export_cadquery(assembly, fmt)
    except Exception as exc:
        logger.info("cadquery %s export unavailable (%s); using mesh serializer", fmt, exc)
        return _export_trimesh(geometry, fmt, z_up=z_up)


def _build_canonical_assembly(geometry, z_up=False):
    """Build all solids from the canonical member/pane list."""
    import cadquery as cq

    W, H = geometry.width_mm, geometry.height_mm
    bar, depth = geometry.profile.bar, geometry.profile.depth
    frame_color = _frame_rgb(getattr(geometry, "frame_colour_hex", None))
    result = cq.Assembly()

    for member in geometry.members:
        if member.orientation == "horizontal":
            length = member.length * W
            thickness = bar
            solid = cq.Workplane("XY").box(length, thickness, depth)
            solid = solid.translate((
                (member.x + member.length / 2) * W - W / 2,
                member.y * H - H / 2,
                depth / 2,
            ))
        else:
            length = member.length * H
            thickness = bar
            solid = cq.Workplane("XY").box(thickness, length, depth)
            solid = solid.translate((
                member.x * W - W / 2,
                (member.y + member.length / 2) * H - H / 2,
                depth / 2,
            ))
        result.add(solid, name=member.id, color=cq.Color(*frame_color))

    for index, pane in enumerate(geometry.panes, 1):
        x0 = pane.x * W + bar
        y0 = pane.y_bottom * H + bar
        x1 = (pane.x + pane.w) * W - bar
        y1 = (pane.y_bottom + pane.h) * H - bar
        if x1 <= x0 or y1 <= y0:
            continue
        infill = cq.Workplane("XY").box(x1 - x0, y1 - y0, _GLASS_THICKNESS)
        infill = infill.translate(((x0 + x1) / 2 - W / 2,
                                   (y0 + y1) / 2 - H / 2,
                                   depth / 2))
        if pane.infill == "panel":
            result.add(infill, name=f"panel-{index}", color=cq.Color(*frame_color))
        else:
            result.add(infill, name=f"glass-{index}", color=cq.Color(.55, .75, .80, .35))

        # Glazing bars are derived from the same pane rectangles in design_json.
        for bar_index, glazing_bar in enumerate(pane.glazing_bars):
            thickness = float(glazing_bar.get("thickness", 18))
            pos = float(glazing_bar.get("pos", .5))
            if glazing_bar.get("type") == "vertical":
                gx = x0 + (x1 - x0) * pos
                bar_solid = cq.Workplane("XY").box(thickness, y1 - y0, depth * .7)
                bar_solid = bar_solid.translate((gx - W / 2, (y0 + y1) / 2 - H / 2, depth * .5))
            else:
                gy = y0 + (y1 - y0) * pos
                bar_solid = cq.Workplane("XY").box(x1 - x0, thickness, depth * .7)
                bar_solid = bar_solid.translate(((x0 + x1) / 2 - W / 2, gy - H / 2, depth * .5))
            result.add(bar_solid, name=f"glazing-bar-{index}-{bar_index}", color=cq.Color(*frame_color))

    return result


def _export_cadquery(assembly, fmt):
    import cadquery as cq

    export_type = {"step": "STEP", "stl": "STL", "glb": "GLTF"}[fmt]

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, f"model.{fmt}")

        exporters = getattr(cq, "exporters", None)
        export_fn = getattr(exporters, "exportAssembly", None) if exporters else None

        if callable(export_fn):
            export_fn(assembly, path, exportType=export_type)
        elif hasattr(assembly, "save"):
            assembly.save(path, exportType=export_type)
        else:
            compound = assembly.toCompound()
            cq.exporters.export(compound, path, exportType=export_type)

        with open(path, "rb") as fh:
            return fh.read()


def _export_trimesh(geometry, fmt, z_up=False):
    import trimesh
    meshes = []
    W, H = geometry.width_mm, geometry.height_mm
    bar, depth = geometry.profile.bar, geometry.profile.depth

    def box(extents, center):
        mesh = trimesh.creation.box(extents=extents)
        mesh.apply_translation(center)
        return mesh

    for member in geometry.members:
        if member.orientation == "horizontal":
            meshes.append(box((member.length * W, bar, depth),
                              ((member.x + member.length / 2) * W - W / 2,
                               member.y * H - H / 2, depth / 2)))
        else:
            meshes.append(box((bar, member.length * H, depth),
                              (member.x * W - W / 2,
                               (member.y + member.length / 2) * H - H / 2,
                               depth / 2)))

    for pane in geometry.panes:
        x0 = pane.x * W + bar
        y0 = pane.y_bottom * H + bar
        x1 = (pane.x + pane.w) * W - bar
        y1 = (pane.y_bottom + pane.h) * H - bar
        if x1 > x0 and y1 > y0:
            meshes.append(box((x1 - x0, y1 - y0, _GLASS_THICKNESS),
                              ((x0 + x1) / 2 - W / 2,
                               (y0 + y1) / 2 - H / 2, depth / 2)))

    scene = trimesh.Scene(meshes)
    if z_up:
        import numpy as np
        rot = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0])
        scene.apply_transform(rot)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, f"model.{fmt}")
        if fmt == "stl":
            combined = trimesh.util.concatenate(meshes)
            combined.export(path, file_type="stl")
        else:
            scene.export(path, file_type="glb")
        with open(path, "rb") as fh:
            return fh.read()


def _frame_rgb(hex_colour):
    try:
        h = (hex_colour or "#6a6a6c").lstrip("#")
        return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)
    except Exception:
        return (.62, .62, .64)