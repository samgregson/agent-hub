export interface DatasetTableRecord {
  id: string;
  position: number;
  sourceKey: string | null;
  value: Record<string, unknown>;
}

export interface DatasetColumn {
  id: string;
  label: string;
  path: string[];
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

export function datasetColumns(
  records: readonly DatasetTableRecord[],
): DatasetColumn[] {
  const paths = new Map<string, string[]>();
  function visit(value: unknown, path: string[], depth: number) {
    if (
      depth > 4 ||
      value === null ||
      Array.isArray(value) ||
      typeof value !== "object"
    ) {
      return;
    }
    for (const [key, nested] of Object.entries(value)) {
      const nestedPath = [...path, key];
      if (scalarText(nested) !== null) {
        paths.set(JSON.stringify(nestedPath), nestedPath);
      } else if (
        nested !== null &&
        typeof nested === "object" &&
        !Array.isArray(nested)
      ) {
        visit(nested, nestedPath, depth + 1);
      }
    }
  }
  for (const record of records) visit(record.value, [], 0);
  return [...paths.values()].map((path) => ({
    id: JSON.stringify(path),
    label: path.join(" / "),
    path,
  }));
}

export function datasetColumnText(
  value: Record<string, unknown>,
  column: DatasetColumn,
): string | null {
  let current: unknown = value;
  for (const key of column.path) {
    if (current === null || Array.isArray(current) || typeof current !== "object") {
      return null;
    }
    current = (current as Record<string, unknown>)[key];
  }
  return scalarText(current);
}

export function filterDatasetRecords<T extends DatasetTableRecord>(
  records: readonly T[],
  query: string,
  columns: readonly (string | DatasetColumn)[],
): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...records];
  return records.filter((record) =>
    [
      record.sourceKey ?? "",
      record.id,
      ...columns.map((column) =>
        typeof column === "string"
          ? scalarText(record.value[column]) ?? ""
          : datasetColumnText(record.value, column) ?? "",
      ),
    ].some((value) => value.toLowerCase().includes(needle)),
  );
}
