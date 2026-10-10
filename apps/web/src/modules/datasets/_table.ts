export interface DatasetTableRecord {
  id: string;
  position: number;
  sourceKey: string | null;
  value: Record<string, unknown>;
}

export function scalarText(value: unknown): string | null {
  if (value === null) return "null";
  if (["string", "number", "boolean"].includes(typeof value)) {
    return String(value);
  }
  return null;
}

export function scalarColumns(
  records: readonly DatasetTableRecord[],
): string[] {
  const columns = new Set<string>();
  for (const record of records) {
    for (const [key, value] of Object.entries(record.value)) {
      if (scalarText(value) !== null) columns.add(key);
    }
  }
  return [...columns];
}

export function filterDatasetRecords<T extends DatasetTableRecord>(
  records: readonly T[],
  query: string,
  columns: readonly string[],
): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...records];
  return records.filter((record) =>
    [
      record.sourceKey ?? "",
      record.id,
      ...columns.map((key) => scalarText(record.value[key]) ?? ""),
    ].some((value) => value.toLowerCase().includes(needle)),
  );
}
