type JsonSchema = Record<string, unknown>;

function schemaObject(value: unknown): JsonSchema | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonSchema)
    : null;
}

function sampleValue(schema: JsonSchema, index: number): unknown {
  if ("const" in schema) return schema.const;
  if (Array.isArray(schema.examples) && schema.examples.length > 0) {
    return schema.examples[0];
  }
  if ("default" in schema) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length > 0)
    return schema.enum[0];

  for (const key of ["oneOf", "anyOf", "allOf"]) {
    const choices = schema[key];
    if (Array.isArray(choices) && choices.length > 0) {
      const selected = schemaObject(choices[0]);
      if (selected) return sampleValue(selected, index);
    }
  }

  const declaredType = schema.type;
  const type = Array.isArray(declaredType)
    ? declaredType.find((item) => item !== "null")
    : declaredType;

  if (type === "object" || schema.properties) {
    const properties = schemaObject(schema.properties) ?? {};
    return Object.fromEntries(
      Object.entries(properties).flatMap(([name, child]) => {
        const childSchema = schemaObject(child);
        return childSchema ? [[name, sampleValue(childSchema, index)]] : [];
      }),
    );
  }

  if (type === "array" || schema.items) {
    const itemSchema = schemaObject(schema.items) ?? {};
    const minItems = typeof schema.minItems === "number" ? schema.minItems : 0;
    const sampleCount = Math.min(3, Math.max(2, minItems));
    return Array.from({ length: sampleCount }, (_, itemIndex) =>
      sampleValue(itemSchema, itemIndex),
    );
  }

  if (type === "integer" || type === "number") {
    const minimum = typeof schema.minimum === "number" ? schema.minimum : 1;
    const exclusiveMinimum =
      typeof schema.exclusiveMinimum === "number"
        ? schema.exclusiveMinimum
        : null;
    const lowerBound =
      exclusiveMinimum === null
        ? minimum
        : Math.max(minimum, exclusiveMinimum + 1);
    const multipleOf =
      typeof schema.multipleOf === "number" ? schema.multipleOf : 1;
    const candidate =
      Math.ceil(lowerBound / multipleOf) * multipleOf + index * multipleOf;
    return type === "integer" ? Math.ceil(candidate) : candidate;
  }

  if (type === "boolean") return true;
  if (type === "null") return null;
  if (type === "string") {
    if (Array.isArray(schema.enum) && schema.enum.length > 0)
      return schema.enum[0];
    if (schema.format === "date") return "2026-01-01";
    if (schema.format === "date-time") return "2026-01-01T00:00:00Z";
    if (schema.format === "email") return "person@example.com";
    const minLength =
      typeof schema.minLength === "number" ? schema.minLength : 0;
    const sample = `Example ${String.fromCharCode(65 + (index % 26))}`;
    return sample.length >= minLength ? sample : sample.padEnd(minLength, "x");
  }

  return null;
}

export function exampleFunctionInputs(inputSchema: JsonSchema): string {
  const example = sampleValue(inputSchema, 0);
  const objectExample =
    example !== null && typeof example === "object" && !Array.isArray(example)
      ? example
      : {};
  return JSON.stringify(objectExample, null, 2);
}
