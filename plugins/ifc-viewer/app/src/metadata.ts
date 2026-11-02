export type Scalar = string | number | boolean | null;
export type MetadataRow = { globalId: string; values: Record<string, Scalar> };
export type View = {
  kind: "ifc.view";
  schemaVersion: "1";
  ifcText: string;
  modelSha256: string;
  metadata: MetadataRow[];
  colourBy: string | null;
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
): Map<string, string> {
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
