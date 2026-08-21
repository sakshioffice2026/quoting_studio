"""
CAD Geometry Validator — Pre-flight checks for DXF/DWG import/export
Validates dimensions, structure, profiles, and output feasibility
"""

from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    ERROR = "error"      # Blocks operation
    WARNING = "warning"  # Allow but flag for review
    INFO = "info"        # Informational


@dataclass
class ValidationIssue:
    """Single validation issue"""
    severity: ValidationSeverity
    code: str
    message: str
    location: str = ""
    suggested_fix: str = ""


@dataclass
class ValidationResult:
    """Complete validation report"""
    is_valid: bool
    issues: List[ValidationIssue]
    stats: Dict[str, any]

    def has_errors(self) -> bool:
        return any(i.severity == ValidationSeverity.ERROR for i in self.issues)

    def has_warnings(self) -> bool:
        return any(i.severity == ValidationSeverity.WARNING for i in self.issues)

    def error_count(self) -> int:
        return len([i for i in self.issues if i.severity == ValidationSeverity.ERROR])

    def warning_count(self) -> int:
        return len([i for i in self.issues if i.severity == ValidationSeverity.WARNING])

    def to_dict(self) -> dict:
        """Serialize for API response"""
        return {
            'is_valid': self.is_valid,
            'errors': self.error_count(),
            'warnings': self.warning_count(),
            'issues': [
                {
                    'severity': i.severity.value,
                    'code': i.code,
                    'message': i.message,
                    'location': i.location,
                    'suggested_fix': i.suggested_fix
                }
                for i in self.issues
            ],
            'stats': self.stats
        }


class DimensionValidator:
    """Validate physical dimensions"""
    
    # Realistic bounds for window components (mm)
    MIN_WIDTH = 400
    MAX_WIDTH = 4000
    MIN_HEIGHT = 400
    MAX_HEIGHT = 3500
    MIN_BAR_WIDTH = 20
    MAX_BAR_WIDTH = 150
    MIN_DEPTH = 40
    MAX_DEPTH = 250

    @staticmethod
    def validate_dimension(value: float, dimension_type: str, unit: str = "mm") -> Optional[ValidationIssue]:
        """Check single dimension validity"""
        
        if value is None or value == 0:
            return ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="INVALID_ZERO_DIM",
                message=f"{dimension_type} cannot be zero or null",
                suggested_fix=f"Set {dimension_type} to a positive value"
            )
        
        if value < 0:
            return ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="NEGATIVE_DIMENSION",
                message=f"{dimension_type} is negative: {value} {unit}",
                suggested_fix=f"Use absolute value: {abs(value)} {unit}"
            )
        
        # Check ranges based on type
        if "width" in dimension_type.lower():
            if value < DimensionValidator.MIN_WIDTH:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="UNDERSIZED_WIDTH",
                    message=f"Width {value}mm below typical minimum {DimensionValidator.MIN_WIDTH}mm",
                    suggested_fix="Verify this is intentional (transom/side light)"
                )
            if value > DimensionValidator.MAX_WIDTH:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="OVERSIZED_WIDTH",
                    message=f"Width {value}mm exceeds typical maximum {DimensionValidator.MAX_WIDTH}mm",
                    suggested_fix="May require structural validation"
                )
        
        if "height" in dimension_type.lower():
            if value < DimensionValidator.MIN_HEIGHT:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="UNDERSIZED_HEIGHT",
                    message=f"Height {value}mm below typical minimum {DimensionValidator.MIN_HEIGHT}mm",
                    suggested_fix="Verify this is intentional"
                )
            if value > DimensionValidator.MAX_HEIGHT:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="OVERSIZED_HEIGHT",
                    message=f"Height {value}mm exceeds typical maximum {DimensionValidator.MAX_HEIGHT}mm",
                    suggested_fix="May require structural validation"
                )
        
        if "bar" in dimension_type.lower() or "profile" in dimension_type.lower():
            if value < DimensionValidator.MIN_BAR_WIDTH:
                return ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="UNDERSIZED_BAR",
                    message=f"Bar width {value}mm is too thin (minimum {DimensionValidator.MIN_BAR_WIDTH}mm)",
                    suggested_fix=f"Use bar width ≥ {DimensionValidator.MIN_BAR_WIDTH}mm"
                )
            if value > DimensionValidator.MAX_BAR_WIDTH:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="OVERSIZED_BAR",
                    message=f"Bar width {value}mm is unusually thick",
                    suggested_fix="Verify against system specifications"
                )
        
        if "depth" in dimension_type.lower():
            if value < DimensionValidator.MIN_DEPTH:
                return ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INSUFFICIENT_DEPTH",
                    message=f"Depth {value}mm below minimum {DimensionValidator.MIN_DEPTH}mm",
                    suggested_fix=f"Increase depth to ≥ {DimensionValidator.MIN_DEPTH}mm"
                )
            if value > DimensionValidator.MAX_DEPTH:
                return ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="EXCESSIVE_DEPTH",
                    message=f"Depth {value}mm exceeds typical maximum {DimensionValidator.MAX_DEPTH}mm",
                    suggested_fix="Verify system design allows this depth"
                )
        
        return None  # Valid


class ProfileValidator:
    """Validate CAD profiles"""

    @staticmethod
    def validate_profile_geometry(profile: dict) -> List[ValidationIssue]:
        """Check profile completeness and validity"""
        issues = []
        
        # Required fields
        required = ['bar', 'depth', 'wall']
        for field in required:
            if field not in profile or profile[field] is None:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_PROFILE_FIELD",
                    message=f"Profile missing required field: {field}",
                    suggested_fix=f"Load profile from database or specify {field}"
                ))
        
        # Validate each dimension
        if 'bar' in profile:
            dim_issue = DimensionValidator.validate_dimension(profile['bar'], "Bar width")
            if dim_issue:
                issues.append(dim_issue)
        
        if 'depth' in profile:
            dim_issue = DimensionValidator.validate_dimension(profile['depth'], "Depth")
            if dim_issue:
                issues.append(dim_issue)
        
        if 'wall' in profile:
            if profile['wall'] < 1:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="INVALID_WALL_THICKNESS",
                    message=f"Wall thickness {profile['wall']}mm is too thin",
                    suggested_fix="Wall thickness must be ≥ 1mm"
                ))
        
        # Profile proportions check
        if 'bar' in profile and 'depth' in profile:
            bar, depth = profile['bar'], profile['depth']
            if depth < bar:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="UNUSUAL_PROPORTION",
                    message=f"Depth ({depth}mm) is less than bar width ({bar}mm)",
                    suggested_fix="Verify profile orientation is correct"
                ))
        
        return issues

    @staticmethod
    def validate_profile_exists(profile_code: str, available_profiles: List[str]) -> Optional[ValidationIssue]:
        """Check if profile exists in database"""
        if profile_code not in available_profiles:
            return ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="PROFILE_NOT_FOUND",
                message=f"Profile '{profile_code}' not found in database",
                suggested_fix=f"Available profiles: {', '.join(available_profiles[:5])}..."
            )
        return None


class PaneValidator:
    """Validate pane/cell definitions"""

    @staticmethod
    def validate_pane(pane: dict, window_width: float, window_height: float) -> List[ValidationIssue]:
        """Check single pane validity"""
        issues = []
        
        # Required fields
        if 'x_norm' not in pane or 'y_norm' not in pane:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="MISSING_PANE_POSITION",
                message="Pane missing normalized position (x_norm, y_norm)",
                suggested_fix="Specify pane position as normalized coordinates (0-1)"
            ))
        
        if 'w_norm' not in pane or 'h_norm' not in pane:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="MISSING_PANE_SIZE",
                message="Pane missing normalized size (w_norm, h_norm)",
                suggested_fix="Specify pane size as normalized coordinates (0-1)"
            ))
        
        # Validate normalized coordinates (0-1 range)
        for key in ['x_norm', 'y_norm', 'w_norm', 'h_norm']:
            if key in pane:
                val = pane[key]
                if val < 0 or val > 1:
                    issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="INVALID_NORMALIZED_COORD",
                        message=f"{key}={val} is outside [0, 1] range",
                        suggested_fix="Normalize coordinate: pixel_value / total_dimension"
                    ))
        
        # Check pane doesn't exceed frame bounds
        if all(k in pane for k in ['x_norm', 'y_norm', 'w_norm', 'h_norm']):
            x, y, w, h = pane['x_norm'], pane['y_norm'], pane['w_norm'], pane['h_norm']
            if x + w > 1.0:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="PANE_EXCEEDS_BOUNDS_X",
                    message=f"Pane extends beyond right edge (x={x}, w={w})",
                    suggested_fix="Adjust pane position or width"
                ))
            if y + h > 1.0:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="PANE_EXCEEDS_BOUNDS_Y",
                    message=f"Pane extends beyond top edge (y={y}, h={h})",
                    suggested_fix="Adjust pane position or height"
                ))
        
        # Validate opener type
        valid_openers = ['Fixed light', 'Side hung left', 'Side hung right', 'Top hung', 'Bottom hung']
        if 'opener_type' in pane and pane['opener_type'] not in valid_openers:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="UNKNOWN_OPENER_TYPE",
                message=f"Opener type '{pane['opener_type']}' not recognized",
                suggested_fix=f"Use one of: {', '.join(valid_openers)}"
            ))
        
        # Validate glazing type
        valid_glazing = ['Single glazed', 'Double, Low-E', 'Double, standard', 'Triple glazed']
        if 'glazing_type' in pane and pane['glazing_type'] not in valid_glazing:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="UNKNOWN_GLAZING_TYPE",
                message=f"Glazing type '{pane['glazing_type']}' not recognized",
                suggested_fix=f"Use one of: {', '.join(valid_glazing)}"
            ))
        
        return issues


class WindowValidator:
    """Validate complete window definition"""

    @staticmethod
    def validate_window_for_export(window: dict, panes: List[dict], profile: dict) -> ValidationResult:
        """Pre-export validation"""
        issues = []
        stats = {
            'width_mm': window.get('width_mm'),
            'height_mm': window.get('height_mm'),
            'profile_code': window.get('profile_code', 'unknown'),
            'pane_count': len(panes),
            'estimated_sheet_area_m2': 0
        }
        
        # Check window dimensions
        if 'width_mm' in window:
            dim_issue = DimensionValidator.validate_dimension(window['width_mm'], "Window width")
            if dim_issue:
                issues.append(dim_issue)
        
        if 'height_mm' in window:
            dim_issue = DimensionValidator.validate_dimension(window['height_mm'], "Window height")
            if dim_issue:
                issues.append(dim_issue)
        
        # Validate profile
        profile_issues = ProfileValidator.validate_profile_geometry(profile)
        issues.extend(profile_issues)
        
        # Validate all panes
        w, h = window.get('width_mm', 0), window.get('height_mm', 0)
        for i, pane in enumerate(panes):
            pane_issues = PaneValidator.validate_pane(pane, w, h)
            for issue in pane_issues:
                issue.location = f"Pane {i}"
            issues.extend(pane_issues)
        
        # Check DXF sheet fit (A1 = 841x594mm)
        if w and h:
            # Add margins for sections
            total_width = w + profile.get('depth', 100) + 200  # sections + margins
            total_height = h + 300  # space for schedule
            
            stats['estimated_sheet_area_m2'] = round((total_width * total_height) / 1_000_000, 3)
            
            if total_width > 1500:  # exceeds typical sheet width
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="DRAWING_TOO_WIDE",
                    message=f"Drawing width ~{total_width}mm may not fit standard sheets",
                    suggested_fix="Consider splitting into multiple sheets or reducing scale"
                ))
            
            if total_height > 1200:  # exceeds typical sheet height
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="DRAWING_TOO_TALL",
                    message=f"Drawing height ~{total_height}mm may not fit standard sheets",
                    suggested_fix="Consider splitting into multiple sheets"
                ))
        
        # Material validation
        if 'material' in window:
            valid_materials = ['Aluminium', 'Steel', 'Timber', 'uPVC']
            if window['material'] not in valid_materials:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="UNKNOWN_MATERIAL",
                    message=f"Material '{window['material']}' not recognized",
                    suggested_fix=f"Use one of: {', '.join(valid_materials)}"
                ))
        
        is_valid = not any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            stats=stats
        )

    @staticmethod
    def validate_window_for_import(file_path: str, file_type: str) -> ValidationResult:
        """Pre-import validation (file integrity)"""
        issues = []
        stats = {'file_type': file_type, 'file_size_kb': 0}
        
        # File existence and type
        try:
            import os
            if not os.path.exists(file_path):
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="FILE_NOT_FOUND",
                    message=f"File not found: {file_path}",
                    suggested_fix="Verify file path and ensure file exists"
                ))
                return ValidationResult(is_valid=False, issues=issues, stats=stats)
            
            file_size = os.path.getsize(file_path)
            stats['file_size_kb'] = round(file_size / 1024, 2)
            
            if file_size > 50_000_000:  # 50MB
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="FILE_TOO_LARGE",
                    message=f"File size {stats['file_size_kb']}KB is very large",
                    suggested_fix="Processing may be slow. Consider simplifying the drawing."
                ))
        
        except Exception as e:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="FILE_READ_ERROR",
                message=f"Cannot read file: {str(e)}",
                suggested_fix="Verify file is accessible and not corrupted"
            ))
            return ValidationResult(is_valid=False, issues=issues, stats=stats)
        
        # File format validation
        if file_type.lower() == 'dxf':
            try:
                # Basic DXF header check
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    header = f.read(100)
                    if 'SECTION' not in header or 'HEADER' not in header:
                        issues.append(ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            code="INVALID_DXF_FORMAT",
                            message="File does not appear to be valid DXF format",
                            suggested_fix="Re-export from CAD software as DXF R2000 or later"
                        ))
            except Exception as e:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="DXF_PARSE_ERROR",
                    message=f"Cannot parse DXF: {str(e)}",
                    suggested_fix="Verify file is not corrupted"
                ))
        
        elif file_type.lower() == 'dwg':
            issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                code="DWG_REQUIRES_CONVERTER",
                message="DWG files require ODA File Converter",
                suggested_fix="Ensure ODA File Converter is installed on server"
            ))
        
        is_valid = not any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            stats=stats
        )


class ExportValidator:
    """Validate DXF export output"""

    @staticmethod
    def validate_dxf_output(dxf_bytes: bytes, expected_width: float, expected_height: float) -> ValidationResult:
        """Validate generated DXF before delivery"""
        issues = []
        stats = {'output_size_kb': len(dxf_bytes) / 1024, 'has_layers': False, 'has_dimensions': False}
        
        try:
            # Parse DXF to check structure
            dxf_text = dxf_bytes.decode('utf-8', errors='ignore')
            
            if not dxf_text or len(dxf_text) < 100:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="EMPTY_DXF_OUTPUT",
                    message="Generated DXF appears to be empty",
                    suggested_fix="Check window dimensions and profile data"
                ))
            
            # Check for essential DXF sections
            has_header = 'SECTION' in dxf_text and 'HEADER' in dxf_text
            has_entities = 'ENTITIES' in dxf_text
            has_objects = 'OBJECTS' in dxf_text
            
            if not has_header:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_DXF_HEADER",
                    message="DXF missing HEADER section",
                    suggested_fix="Regenerate using ezdxf library"
                ))
            
            if not has_entities:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    code="MISSING_DXF_ENTITIES",
                    message="DXF has no drawable entities",
                    suggested_fix="Verify window has dimensions and panes"
                ))
            
            # Check for layers
            layer_count = dxf_text.count('AcDbLayerTableRecord')
            stats['has_layers'] = layer_count > 0
            if layer_count == 0:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="NO_LAYERS",
                    message="DXF has no organized layers",
                    suggested_fix="Use layer organization in CAD export"
                ))
            
            # Check for dimensions
            has_dims = 'DIMENSION' in dxf_text or 'DIMSTYLE' in dxf_text
            stats['has_dimensions'] = has_dims
            if not has_dims:
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="NO_DIMENSIONS",
                    message="DXF has no dimensional annotations",
                    suggested_fix="Enable dimension output in export settings"
                ))
            
            # File size sanity check
            if len(dxf_bytes) > 20_000_000:  # 20MB
                issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    code="LARGE_DXF_OUTPUT",
                    message=f"DXF output is {stats['output_size_kb']:.0f}KB (unusually large)",
                    suggested_fix="Check for duplicate geometry or excessive detail"
                ))
        
        except Exception as e:
            issues.append(ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="DXF_VALIDATION_ERROR",
                message=f"Cannot validate DXF: {str(e)}",
                suggested_fix="Contact support"
            ))
        
        is_valid = not any(i.severity == ValidationSeverity.ERROR for i in issues)
        return ValidationResult(
            is_valid=is_valid,
            issues=issues,
            stats=stats
        )


# ════════════════════════════════════════════════════════════════
# Integration helper for Flask routes
# ════════════════════════════════════════════════════════════════

def validate_before_export(window_orm, panes_orm, profile_dict) -> ValidationResult:
    """
    Usage in Flask route:
    
    from cad_geometry_validator import validate_before_export
    
    result = validate_before_export(window, panes, profile)
    if not result.is_valid:
        return jsonify(result.to_dict()), 400
    
    # Proceed with export
    dxf_bytes = generate_window_dxf(window, panes, ...)
    """
    window_dict = {
        'width_mm': window_orm.width_mm,
        'height_mm': window_orm.height_mm,
        'material': window_orm.material,
        'profile_code': getattr(window_orm, 'profile_code', 'unknown')
    }
    
    panes_list = [
        {
            'x_norm': p.x_norm,
            'y_norm': p.y_norm,
            'w_norm': p.w_norm,
            'h_norm': p.h_norm,
            'opener_type': p.opener_type,
            'glazing_type': p.glazing_type
        }
        for p in panes_orm
    ]
    
    return WindowValidator.validate_window_for_export(window_dict, panes_list, profile_dict)


def validate_before_import(file_path: str, file_type: str) -> ValidationResult:
    """
    Usage in Flask route:
    
    from cad_geometry_validator import validate_before_import
    
    result = validate_before_import('/tmp/profile.dxf', 'dxf')
    if not result.is_valid:
        return jsonify(result.to_dict()), 400
    
    # Proceed with import
    """
    return WindowValidator.validate_window_for_import(file_path, file_type)
