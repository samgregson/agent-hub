export type Scalar = string | number | boolean | null;
export type MetadataRow = { globalId: string; values: Record<string, Scalar> };
export type ColourScale = {
  key: string;
  bands: { max: number; colour: string }[];
  aboveColour: string;
};
export type View = {
  kind: "ifc.view";
  schemaVersion: "1";
  ifcText: string;
  modelSha256: string;
  metadata: MetadataRow[];
  colourBy: string | null;
  colourScale?: ColourScale | null;
};
export const palette = [
  "#2563eb",
  "#d97706",
  "#059669",
  "#9333ea",
  "#e11d48",
  "#0891b2",
  "#4f46e5",
  "#a16207",
];
export function valueKey(value: Scalar | undefined): string {
  return value === undefined
    ? "Unassigned"
    : `${typeof value}: ${JSON.stringify(value)}`;
}
export function colourMap(
  rows: MetadataRow[],
  key: string,
  scale?: ColourScale | null,
): Map<string, string> {
  if (scale?.key === key) {
    const result = new Map<string, string>([["Unassigned", "#94a3b8"]]);
    for (const row of rows) {
      const value = row.values[key];
      result.set(
        valueKey(value),
        typeof value === "number" && Number.isFinite(value)
          ? (scale.bands.find((band) => value <= band.max)?.colour ??
              scale.aboveColour)
          : "#94a3b8",
      );
    }
    return result;
  }
  const values = [
    ...new Set([
      "Unassigned",
      ...rows.map((row) =>
        valueKey(Object.hasOwn(row.values, key) ? row.values[key] : undefined),
      ),
    ]),
  ].sort();
  return new Map(
    values.map((value, index) => [
      value,
      value === "Unassigned" ? "#94a3b8" : palette[index % palette.length],
    ]),
  );
}
export function scaleLegend(scale: ColourScale): Map<string, string> {
  const entries: [string, string][] = scale.bands.map((band, index) => [
    index === 0
      ? `≤ ${band.max}`
      : `> ${scale.bands[index - 1].max} and ≤ ${band.max}`,
    band.colour,
  ]);
  entries.push([
    `> ${scale.bands[scale.bands.length - 1].max}`,
    scale.aboveColour,
  ]);
  entries.push(["Unassigned or nonnumeric", "#94a3b8"]);
  return new Map(entries);
}
export function assignMetadata(
  rows: MetadataRow[],
  globalId: string,
  key: string,
  value: Scalar,
): MetadataRow[] {
  if (!key.trim() || key.length > 128)
    throw new Error("Use a metadata name of 1–128 characters.");
  if (typeof value === "number" && !Number.isFinite(value))
    throw new Error("Use a finite number.");
  const existing = rows.find((row) => row.globalId === globalId);
  const values = Object.fromEntries([
    ...Object.entries(existing?.values ?? {}).filter(([name]) => name !== key),
    [key, value],
  ]);
  return [
    ...rows.filter((row) => row.globalId !== globalId),
    { globalId, values },
  ];
}
export function readView(result: unknown): View {
  const raw = result as { payload?: { output?: unknown }; kind?: string };
  const value = (raw?.payload?.output ?? raw) as View;
  if (
    value?.kind !== "ifc.view" ||
    value.schemaVersion !== "1" ||
    typeof value.ifcText !== "string" ||
    !Array.isArray(value.metadata)
  )
    throw new Error("This result is not a supported IFC view.");
  if (value.colourScale != null) {
    const scale = value.colourScale;
    const colour = (item: unknown) =>
      typeof item === "string" && /^#[0-9a-f]{6}$/i.test(item);
    if (
      typeof scale.key !== "string" ||
      !scale.key ||
      !Array.isArray(scale.bands) ||
      !scale.bands.length ||
      scale.bands.length > 20 ||
      !colour(scale.aboveColour) ||
      scale.bands.some(
        (band, index) =>
          !band ||
          typeof band.max !== "number" ||
          !Number.isFinite(band.max) ||
          !colour(band.colour) ||
          (index > 0 && band.max <= scale.bands[index - 1].max),
      )
    )
      throw new Error("Invalid numeric colour scale.");
  }
  const seen = new Set<string>();
  for (const row of value.metadata) {
    if (
      !row ||
      typeof row.globalId !== "string" ||
      seen.has(row.globalId) ||
      !row.values ||
      typeof row.values !== "object" ||
      Array.isArray(row.values)
    )
      throw new Error("Invalid or duplicate metadata GlobalId.");
    seen.add(row.globalId);
    for (const scalar of Object.values(row.values)) {
      if (
        (scalar !== null &&
          !["string", "boolean", "number"].includes(typeof scalar)) ||
        (typeof scalar === "number" && !Number.isFinite(scalar))
      )
        throw new Error("Metadata must contain finite JSON scalars.");
    }
  }
  return value;
}
