import { isImageOutput, type ImageOutput } from "@/modules/media";

export interface FunctionPreviewField {
  name: string;
  description: string;
  unit: string;
  value: unknown;
}

const scalarTypes = new Set(["string", "number", "integer", "boolean", "null"]);

export function functionPreviewFields(
  value: unknown,
  schema: Record<string, unknown>,
): FunctionPreviewField[] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }
  const properties = schema.properties;
  if (
    !properties ||
    typeof properties !== "object" ||
    Array.isArray(properties)
  ) {
    return [];
  }
  return Object.entries(properties as Record<string, unknown>).flatMap(
    ([name, property]) => {
      if (
        property === null ||
        typeof property !== "object" ||
        Array.isArray(property)
      ) {
        return [];
      }
      const field = property as Record<string, unknown>;
      const declaredTypes = Array.isArray(field.type)
        ? field.type
        : [field.type];
      if (!declaredTypes.some((type) => scalarTypes.has(String(type)))) {
        return [];
      }
      const fieldValue = (value as Record<string, unknown>)[name];
      if (!Object.hasOwn(value, name)) {
        return [];
      }
      if (fieldValue !== null && typeof fieldValue === "object") {
        return [];
      }
      return [
        {
          name,
          description:
            typeof field.description === "string" ? field.description : "",
          unit:
            typeof field.unit === "string"
              ? field.unit
              : typeof field["x-unit"] === "string"
                ? field["x-unit"]
                : "",
          value: fieldValue,
        },
      ];
    },
  );
}

export function functionPreviewImage(value: unknown): ImageOutput | null {
  if (isImageOutput(value)) return value;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const image = (value as Record<string, unknown>).image;
  return isImageOutput(image) ? image : null;
}

export function functionPreviewSummary(value: unknown): unknown {
  if (isImageOutput(value)) {
    return {
      kind: value.kind,
      mimeType: value.mimeType,
      altText: value.altText,
      imageAvailable: true,
    };
  }
  if (Array.isArray(value)) return value.map(functionPreviewSummary);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        functionPreviewSummary(item),
      ]),
    );
  }
  return value;
}

const readableSummaryLimits = { depth: 2, entries: 4, characters: 360 };

export function readableFunctionExample(value: unknown): string {
  const summarize = (item: unknown, depth = 0): string => {
    if (item === null) return "none";
    if (typeof item === "string") {
      return item.length > 60 ? `“${item.slice(0, 57)}…”` : `“${item}”`;
    }
    if (typeof item !== "object") return String(item);
    if (Array.isArray(item)) {
      if (depth >= 3) return `List with ${item.length} items`;
      const preview = item
        .slice(0, 3)
        .map((child) => summarize(child, depth + 1));
      return `List (${item.length} items: ${preview.join("; ")}${item.length > preview.length ? "; …" : ""})`;
    }
    const entries = Object.entries(item as Record<string, unknown>);
    if (depth >= 3) return `Object with ${entries.length} fields`;
    const preview = entries
      .slice(0, 3)
      .map(([key, child]) => `${key}: ${summarize(child, depth + 1)}`);
    return `Object (${preview.join("; ")}${entries.length > preview.length ? "; …" : ""})`;
  };
  const summary = summarize(value);
  return summary.length > 180 ? `${summary.slice(0, 177)}…` : summary;
}

function readableValue(value: unknown, depth: number): string {
  if (isImageOutput(value)) return `Image: ${value.altText || value.mimeType}`;
  if (value === null) return "none";
  if (typeof value === "string") {
    return value.length > 80 ? `${value.slice(0, 77)}…` : `“${value}”`;
  }
  if (typeof value !== "object") return String(value);
  if (depth >= readableSummaryLimits.depth) {
    return Array.isArray(value)
      ? `List with ${value.length} items`
      : `Object with ${Object.keys(value).length} fields`;
  }
  if (Array.isArray(value)) {
    const shown = value
      .slice(0, readableSummaryLimits.entries)
      .map((item) => readableValue(item, depth + 1));
    const remaining = value.length - shown.length;
    return `List (${value.length} items): ${shown.join("; ")}${remaining > 0 ? `; and ${remaining} more` : ""}`;
  }
  const entries = Object.entries(value as Record<string, unknown>);
  const shown = entries
    .slice(0, readableSummaryLimits.entries)
    .map(([key, item]) => `${key}: ${readableValue(item, depth + 1)}`);
  const remaining = entries.length - shown.length;
  return `${shown.join("; ")}${remaining > 0 ? `; and ${remaining} more fields` : ""}`;
}

export function functionPreviewReadableSummary(
  value: unknown,
  excludedKeys: string[] = [],
): string | null {
  const summaryValue =
    excludedKeys.length > 0 &&
    value !== null &&
    typeof value === "object" &&
    !Array.isArray(value)
      ? Object.fromEntries(
          Object.entries(value as Record<string, unknown>).filter(
            ([key]) => !excludedKeys.includes(key),
          ),
        )
      : value;
  if (
    summaryValue !== null &&
    typeof summaryValue === "object" &&
    !Array.isArray(summaryValue) &&
    Object.keys(summaryValue).length === 0
  ) {
    return null;
  }
  const summary = readableValue(summaryValue, 0);
  return summary.length > readableSummaryLimits.characters
    ? `${summary.slice(0, readableSummaryLimits.characters - 1)}…`
    : summary;
}
