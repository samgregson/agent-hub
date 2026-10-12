from pathlib import Path

from fastmcp import FastMCP
from fastmcp.apps import AppConfig, app_config_to_meta_dict

CANTILEVER_TIP_LOAD_TOOL_NAME = "calculate_cantilever_tip_load"
BEAM_DEFLECTION_TOOL_NAME = "check_uniform_beam_deflection"
SIZE_FOR_DEFLECTION_TOOL_NAME = "size_for_deflection"
DRAFT_BEAM_REVIEW_NOTE_TOOL_NAME = "draft_beam_review_note"
CALCULATION_APP_RESOURCE_URI = "ui://agent-hub-reference-calculation/cantilever.html"
_APP_PATH = Path(__file__).parents[2] / "app" / "cantilever-view.html"


def create_reference_calculation_server() -> FastMCP:
    """Create the portable calculation Plugin without starting a transport."""
    mcp = FastMCP("agent-hub-reference-calculation")

    @mcp.tool(name=CANTILEVER_TIP_LOAD_TOOL_NAME, annotations={"idempotentHint": True})
    async def calculate_cantilever_tip_load(
        length_m: float, tip_load_kn: float
    ) -> dict[str, object]:
        """Calculate fixed-end moment for a cantilever with one tip point load.

        Inputs are documented in metres and kilonewtons. The result is a normal,
        structured invalid result when either quantity is non-positive.
        """
        validation = {"status": "valid", "warnings": []}
        if length_m <= 0 or tip_load_kn <= 0:
            warnings: list[str] = []
            if length_m <= 0:
                warnings.append("Length must be greater than zero metres.")
            if tip_load_kn <= 0:
                warnings.append("Tip load must be greater than zero kilonewtons.")
            validation = {"status": "invalid", "warnings": warnings}

        return {
            "calculation": {
                "kind": "cantileverTipLoad",
                "formula": "M_max = P × L",
                "length": {"value": float(length_m), "unit": "m"},
                "tipLoad": {"value": float(tip_load_kn), "unit": "kN"},
                "maximumMoment": {"value": float(tip_load_kn * length_m), "unit": "kN·m"},
            },
            "validation": validation,
        }

    @mcp.tool(name=BEAM_DEFLECTION_TOOL_NAME, annotations={"idempotentHint": True})
    async def check_uniform_beam_deflection(
        beam_ref: str,
        span_m: float,
        imposed_load_kn_m2: float,
        tributary_width_m: float,
        elastic_modulus_gpa: float,
        inertia_mm4: float,
        deflection_limit_ratio: float,
    ) -> dict[str, object]:
        """Check a simply supported beam under full-span uniform imposed load.

        This one check calculates 5wL^4/(384EI), converts the floor area load to
        line load, and compares against the caller-supplied span ratio. It is not
        a beam design or code-compliance verdict.

        Args:
            beam_ref: User-provided beam identifier.
            span_m: Clear analytical span in metres.
            imposed_load_kn_m2: Uniform imposed floor load in kilonewtons per square metre.
            tributary_width_m: Floor width carried by the beam, in metres.
            elastic_modulus_gpa: User-supplied elastic modulus in gigapascals.
            inertia_mm4: Trial major-axis second moment of area in millimetres to the fourth.
            deflection_limit_ratio: User-supplied span divisor, such as 360 for L/360.
        """
        values = {
            "span_m": span_m,
            "imposed_load_kn_m2": imposed_load_kn_m2,
            "tributary_width_m": tributary_width_m,
            "elastic_modulus_gpa": elastic_modulus_gpa,
            "inertia_mm4": inertia_mm4,
            "deflection_limit_ratio": deflection_limit_ratio,
        }
        errors = [
            f"{name} must be greater than zero." for name, value in values.items() if value <= 0
        ]
        context: dict[str, object] = {"beam_ref": beam_ref, **values}
        if errors:
            return {**context, "validation": {"status": "invalid", "errors": errors}}

        span_mm = span_m * 1000
        line_load_n_per_mm = imposed_load_kn_m2 * tributary_width_m
        elastic_modulus_n_per_mm2 = elastic_modulus_gpa * 1000
        maximum_deflection_mm = (
            5 * line_load_n_per_mm * span_mm**4 / (384 * elastic_modulus_n_per_mm2 * inertia_mm4)
        )
        limit_mm = span_mm / deflection_limit_ratio
        return {
            **context,
            "line_load_n_per_mm": line_load_n_per_mm,
            "maximum_deflection_mm": maximum_deflection_mm,
            "limit_mm": limit_mm,
            "check_status": "passes" if maximum_deflection_mm <= limit_mm else "fails",
            "method": "5wL^4/(384EI)",
            "validation": {"status": "valid", "warnings": []},
            "scope": "This result covers only the stated imposed-load deflection check.",
        }

    @mcp.tool(name=SIZE_FOR_DEFLECTION_TOOL_NAME, annotations={"idempotentHint": True})
    async def size_for_deflection(
        beam_ref: str,
        span_m: float,
        imposed_load_kn_m2: float,
        tributary_width_m: float,
        elastic_modulus_gpa: float,
        limit_mm: float,
        trial_inertia_mm4: float,
        trial_deflection_mm: float,
    ) -> dict[str, object]:
        """Calculate the minimum inertia for the supplied deflection check only.

        Args:
            beam_ref: User-provided beam identifier.
            span_m: Clear analytical span in metres.
            imposed_load_kn_m2: Uniform imposed floor load in kilonewtons per square metre.
            tributary_width_m: Floor width carried by the beam, in metres.
            elastic_modulus_gpa: User-supplied elastic modulus in gigapascals.
            limit_mm: User-supplied maximum deflection for this check, in millimetres.
            trial_inertia_mm4: Current trial second moment of area in millimetres to the fourth.
            trial_deflection_mm: Calculated trial deflection in millimetres.
        """
        values = {
            "span_m": span_m,
            "imposed_load_kn_m2": imposed_load_kn_m2,
            "tributary_width_m": tributary_width_m,
            "elastic_modulus_gpa": elastic_modulus_gpa,
            "limit_mm": limit_mm,
            "trial_inertia_mm4": trial_inertia_mm4,
        }
        errors = [
            f"{name} must be greater than zero." for name, value in values.items() if value <= 0
        ]
        context: dict[str, object] = {
            "beam_ref": beam_ref,
            **values,
            "trial_deflection_mm": trial_deflection_mm,
        }
        if errors:
            return {**context, "validation": {"status": "invalid", "errors": errors}}

        span_mm = span_m * 1000
        line_load_n_per_mm = imposed_load_kn_m2 * tributary_width_m
        elastic_modulus_n_per_mm2 = elastic_modulus_gpa * 1000
        minimum_inertia_mm4 = (
            5 * line_load_n_per_mm * span_mm**4 / (384 * elastic_modulus_n_per_mm2 * limit_mm)
        )
        return {
            "beam_ref": beam_ref,
            "span_m": span_m,
            "imposed_load_kn_m2": imposed_load_kn_m2,
            "tributary_width_m": tributary_width_m,
            "elastic_modulus_gpa": elastic_modulus_gpa,
            "limit_mm": limit_mm,
            "trial_inertia_mm4": trial_inertia_mm4,
            "trial_deflection_mm": trial_deflection_mm,
            "minimum_inertia_mm4": minimum_inertia_mm4,
        }

    @mcp.tool(name=DRAFT_BEAM_REVIEW_NOTE_TOOL_NAME, annotations={"idempotentHint": True})
    async def draft_beam_review_note(
        beam_ref: str,
        span_m: float,
        imposed_load_kn_m2: float,
        tributary_width_m: float,
        elastic_modulus_gpa: float,
        limit_mm: float,
        trial_inertia_mm4: float,
        trial_deflection_mm: float,
        minimum_inertia_mm4: float,
    ) -> dict[str, object]:
        """Draft an inspectable review note; it does not approve or publish it.

        Args:
            beam_ref: User-provided beam identifier.
            span_m: Clear analytical span in metres.
            imposed_load_kn_m2: Uniform imposed floor load in kilonewtons per square metre.
            tributary_width_m: Floor width carried by the beam, in metres.
            elastic_modulus_gpa: User-supplied elastic modulus in gigapascals.
            limit_mm: User-supplied maximum deflection for this check, in millimetres.
            trial_inertia_mm4: Current trial second moment of area in millimetres to the fourth.
            trial_deflection_mm: Calculated trial deflection in millimetres.
            minimum_inertia_mm4: Calculated threshold inertia in millimetres to the fourth.
        """
        status = "passes" if trial_deflection_mm <= limit_mm else "fails"
        note = (
            f"{beam_ref} {status} the stated imposed-load deflection check: "
            f"{trial_deflection_mm:.2f} mm against a {limit_mm:.2f} mm limit. "
            f"The calculated minimum inertia for this check is "
            f"{minimum_inertia_mm4 / 1_000_000:.3f} × 10⁶ mm⁴. "
            "Verify the selected section's published properties and complete all other checks."
        )
        return {
            "beam_ref": beam_ref,
            "note": note,
            "review_only": True,
            "inputs": {
                "span_m": span_m,
                "imposed_load_kn_m2": imposed_load_kn_m2,
                "tributary_width_m": tributary_width_m,
                "elastic_modulus_gpa": elastic_modulus_gpa,
                "limit_mm": limit_mm,
                "trial_inertia_mm4": trial_inertia_mm4,
                "trial_deflection_mm": trial_deflection_mm,
                "minimum_inertia_mm4": minimum_inertia_mm4,
            },
        }

    @mcp.resource(
        uri=CALCULATION_APP_RESOURCE_URI,
        name="Cantilever moment view",
        description="An editable cantilever beam calculation view.",
        mime_type="text/html;profile=mcp-app",
        annotations={"readOnlyHint": True, "idempotentHint": True},
        meta={"ui": app_config_to_meta_dict(AppConfig())},
    )
    async def cantilever_view() -> str:
        return _APP_PATH.read_text(encoding="utf-8")

    return mcp


def main() -> None:
    create_reference_calculation_server().run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
