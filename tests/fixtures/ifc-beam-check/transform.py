def transform(inputs, parameters):
    """Example imposed-load deflection check; not a complete beam design."""
    objects = {o["globalId"]: o for o in inputs["objects"] if o["ifcType"] == "IfcBeam"}
    rows = inputs["beam_inputs"]
    assigned = {}
    for row in rows:
        key = row["globalId"]
        if key not in objects or key in assigned:
            raise ValueError("Unknown or duplicate beam GlobalId: " + key)
        assigned[key] = row
    required = (
        "span_m",
        "imposed_load_kn_m2",
        "tributary_width_m",
        "elastic_modulus_gpa",
        "inertia_mm4",
        "deflection_limit_ratio",
    )
    metadata = []
    for key in objects:
        row = assigned.get(key, {})
        missing = [name for name in (*required, "support_condition") if name not in row]
        values = {"status": "missing_inputs", "missing_inputs": ", ".join(missing)}
        if not missing:
            if row["support_condition"] != "simply_supported":
                raise ValueError("Only simply_supported beams are covered")
            for name in required:
                value = row[name]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                    raise ValueError(name + " must be a positive number")
            span_mm = row["span_m"] * 1000
            load = row["imposed_load_kn_m2"] * row["tributary_width_m"]
            stiffness = row["elastic_modulus_gpa"] * 1000 * row["inertia_mm4"]
            deflection = 5 * load * span_mm**4 / (384 * stiffness)
            limit = span_mm / row["deflection_limit_ratio"]
            values = {
                "status": "passes" if deflection <= limit else "fails",
                "deflection_mm": deflection,
                "limit_mm": limit,
                "utilisation": deflection / limit,
                "scope": "Simply supported, uniform imposed-load deflection only",
            }
        metadata.append({"globalId": key, "values": values})
    return {"metadata": metadata}
