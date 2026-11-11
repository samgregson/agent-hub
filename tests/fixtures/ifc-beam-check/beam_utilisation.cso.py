from typing import Annotated
from cso_python import calculation, section, symbol


@calculation(id="illustrative-beam-utilisation", title="Illustrative beam utilisation")
@section(id="utilisation", title="Demand-to-capacity ratios")
def beam_utilisation(
    axial_kN: Annotated[float, symbol(glyph="N_{Ed}", description="Axial demand", unit="kN")],
    axial_capacity_kN: Annotated[
        float, symbol(glyph="N_{Rd}", description="Axial capacity", unit="kN")
    ],
    moment_kNm: Annotated[float, symbol(glyph="M_{Ed}", description="Moment demand", unit="kNm")],
    moment_capacity_kNm: Annotated[
        float, symbol(glyph="M_{Rd}", description="Moment capacity", unit="kNm")
    ],
):
    utilisation: Annotated[
        float, symbol(glyph="U_{beam}", description="Illustrative utilisation", unit="-")
    ] = abs(axial_kN) / axial_capacity_kN + abs(moment_kNm) / moment_capacity_kNm
    return {"utilisation": utilisation}
