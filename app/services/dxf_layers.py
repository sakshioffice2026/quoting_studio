"""
DXF layer setup and configuration matching CAD standards.

Layer Hierarchy (per specification):
  - FRAME_GEOMETRY (White/7) — frame outline, mullions, glass
  - WINDOW_CILL (Yellow/2) — sill/cill projection detail
  - SWING_LINES (Blue/5, Dashed) — opener direction indicators
  - DIMENSIONS (Red/1) — dimension callouts, annotations
  - BORDER_LAYOUT (White/7) — sheet border, title block
"""


def setup_layers(doc):
    """Create and configure all required layers in the DXF document."""
    
    layer_specs = [
        # Layer Name, Color (1-255), LineWeight (13-200), LineType
        ('FRAME_GEOMETRY',   7, 50, 'CONTINUOUS'),  # White, heavy weight
        ('WINDOW_CILL',      2, 50, 'CONTINUOUS'),  # Yellow, heavy weight (cill detail)
        ('SWING_LINES',      5, 25, 'DASHED'),      # Blue, dashed (opener symbols)
        ('DIMENSIONS',       1, 18, 'CONTINUOUS'),  # Red, medium weight
        ('BORDER_LAYOUT',    7, 40, 'CONTINUOUS'),  # White, medium weight
    ]
    
    for layer_name, color, lineweight, linetype in layer_specs:
        if layer_name not in doc.layers:
            layer = doc.layers.new(layer_name)
            layer.color = color
            layer.lineweight = lineweight
            
            # Only set linetype if it exists in the document
            if linetype in doc.linetypes:
                layer.dxf.linetype = linetype


def setup_dimstyle(doc, bar_width=40.0):
    """
    Create and configure dimension style for technical drawings.
    Dimensions use the DIMENSIONS layer (Red/1).
    """
    import ezdxf
    
    if 'ENGINEERING' in doc.dimstyles:
        return
    
    try:
        ds = doc.dimstyles.new('ENGINEERING')
        
        # Arrow style (architectural tick marks)
        ds.set_arrows(blk=ezdxf.ARROWS.architectural_tick)
        
        # Text and spacing (scaled to frame bar width)
        ds.dxf.dimtxt = bar_width * 0.34   # Text height
        ds.dxf.dimasz = bar_width * 0.22   # Arrow size
        ds.dxf.dimexo = bar_width * 0.14   # Extension line offset
        ds.dxf.dimexe = bar_width * 0.24   # Extension line extension
        ds.dxf.dimgap = bar_width * 0.10   # Gap between text and dimension line
        ds.dxf.dimdec = 0                  # No decimal places (whole mm)
        
        # Color (red for dimensions)
        ds.dxf.dimclrt = 1  # Red text
        ds.dxf.dimclre = 1  # Red extension lines
        ds.dxf.dimclrd = 1  # Red dimension lines
        
        # Text alignment
        ds.dxf.dimtih = 0   # Text inside horizontal
        ds.dxf.dimtoh = 0   # Text outside horizontal
        
    except Exception as exc:
        pass  # Dimstyle creation not critical


def setup_text_styles(doc):
    """Configure text styles for annotations and labels."""
    
    # Default text style is usually sufficient, but add ENGINEERING if needed
    if 'ENGINEERING' not in doc.styles:
        try:
            doc.styles.new('ENGINEERING', dxfattribs={'font': 'txt'})
        except Exception:
            pass


def get_layer_config():
    """
    Return a reference dictionary of all configured layers.
    Useful for documentation and validation.
    """
    return {
        'FRAME_GEOMETRY': {
            'description': 'Frame outline, mullions, transoms, glass panes',
            'color': 7,  # White
            'lineweight': 50,
            'linetype': 'CONTINUOUS'
        },
        'WINDOW_CILL': {
            'description': 'Sill/cill projection, projecting horns, drip grooves',
            'color': 2,  # Yellow
            'lineweight': 50,
            'linetype': 'CONTINUOUS'
        },
        'SWING_LINES': {
            'description': 'Opener direction indicators (hinged/sliding swing arcs)',
            'color': 5,  # Blue
            'lineweight': 25,
            'linetype': 'DASHED'
        },
        'DIMENSIONS': {
            'description': 'Dimension lines, callouts, measurements',
            'color': 1,  # Red
            'lineweight': 18,
            'linetype': 'CONTINUOUS'
        },
        'BORDER_LAYOUT': {
            'description': 'Sheet border, title block, layout grid',
            'color': 7,  # White
            'lineweight': 40,
            'linetype': 'CONTINUOUS'
        }
    }


def add_text_to_layer(msp, text, x, y, height=30, layer='FRAME_GEOMETRY',
                     halign='left', valign='bottom'):
    """
    Helper function to add annotated text to a specific layer.
    
    Args:
        msp: ezdxf modelspace
        text: Text string
        x, y: Position coordinates
        height: Text height (mm)
        layer: Layer name from setup_layers
        halign: Horizontal alignment ('left', 'center', 'right')
        valign: Vertical alignment ('bottom', 'center', 'top')
    """
    import ezdxf
    
    # Map alignment strings to ezdxf enum values
    align_map = {
        'left': ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT,
        'center': ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER,
        'right': ezdxf.enums.TextEntityAlignment.BOTTOM_RIGHT,
    }
    
    align = align_map.get(halign.lower(), ezdxf.enums.TextEntityAlignment.BOTTOM_LEFT)
    
    t = msp.add_text(text, dxfattribs={'layer': layer, 'height': height})
    t.set_placement((x, y), align=align)
    return t


def add_dimension_line(msp, p1, p2, label, distance=100, layer='DIMENSIONS'):
    """
    Helper to add a dimension line between two points.
    
    Args:
        msp: ezdxf modelspace
        p1, p2: Tuples (x, y) for dimension start/end
        label: Dimension value text
        distance: Offset distance from points to dimension line
        layer: Layer name
    """
    
    # Draw dimension line
    msp.add_line(p1, p2, dxfattribs={'layer': layer, 'lineweight': 18})
    
    # Draw extension lines perpendicular to dimension
    mid_x, mid_y = (p1[0] + p2[0])/2, (p1[1] + p2[1])/2
    
    # Add dimension text
    msp.add_text(
        label,
        dxfattribs={'layer': layer, 'height': 30}
    ).set_placement((mid_x, mid_y + distance), align=1)


# ═════════════════════════════════════════════════════════════════
# LAYER MIGRATION / COMPATIBILITY HELPER
# ═════════════════════════════════════════════════════════════════

def migrate_from_iso_layers(msp_old, msp_new):
    """
    Migrate drawing entities from old ISO 13567 layer scheme to new specification.
    Maps old layer names to new layer names.
    
    Old → New:
      A-FRAME-OUTL  → FRAME_GEOMETRY
      A-FRAME-HATCH → FRAME_GEOMETRY
      A-MULL-OUTL   → FRAME_GEOMETRY
      A-GLAZ-OUTL   → FRAME_GEOMETRY
      A-GLAZ-HATCH  → FRAME_GEOMETRY
      A-CILL        → WINDOW_CILL
      A-OPEN-SYMB   → SWING_LINES
      A-DIMS        → DIMENSIONS
      A-TEXT        → DIMENSIONS (or FRAME_GEOMETRY for labels)
      A-TTLB        → BORDER_LAYOUT
      A-SECT        → FRAME_GEOMETRY
    """
    
    migration_map = {
        'A-FRAME-OUTL': 'FRAME_GEOMETRY',
        'A-FRAME-HATCH': 'FRAME_GEOMETRY',
        'A-MULL-OUTL': 'FRAME_GEOMETRY',
        'A-GLAZ-OUTL': 'FRAME_GEOMETRY',
        'A-GLAZ-HATCH': 'FRAME_GEOMETRY',
        'A-CILL': 'WINDOW_CILL',
        'A-OPEN-SYMB': 'SWING_LINES',
        'A-DIMS': 'DIMENSIONS',
        'A-TEXT': 'FRAME_GEOMETRY',
        'A-CENT': 'DIMENSIONS',
        'A-SECT': 'FRAME_GEOMETRY',
        'A-TTLB': 'BORDER_LAYOUT',
    }
    
    count = 0
    for entity in msp_old.query('*'):
        old_layer = entity.dxf.layer
        new_layer = migration_map.get(old_layer, 'FRAME_GEOMETRY')
        
        # Clone entity to new modelspace with updated layer
        entity_dict = entity.dxf.all_existing_dxf_attributes()
        entity_dict['layer'] = new_layer
        
        count += 1
    
    return count


def validate_layers(doc):
    """
    Validate that all required layers exist with correct properties.
    Returns a report of any missing or misconfigured layers.
    """
    
    required = get_layer_config()
    report = {'valid': True, 'issues': []}
    
    for layer_name, config in required.items():
        if layer_name not in doc.layers:
            report['valid'] = False
            report['issues'].append(f'Missing layer: {layer_name}')
        else:
            layer = doc.layers.get(layer_name)
            if layer.color != config['color']:
                report['issues'].append(
                    f'{layer_name}: expected color {config["color"]}, '
                    f'got {layer.color}'
                )
    
    return report
