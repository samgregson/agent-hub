"use client";

import { Field } from "@/shared/ui";
import type { ReactNode } from "react";

import styles from "./functions.module.css";

type JsonSchema = Record<string, unknown>;
type InputValues = Record<string, unknown>;

function objectSchema(value: unknown): JsonSchema | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonSchema)
    : null;
}

function schemaType(schema: JsonSchema): string | null {
  const type = schema.type;
  return typeof type === "string" ? type : null;
}

function supported(schema: JsonSchema): boolean {
  const type = schemaType(schema);
  if (
    type === "string" ||
    type === "number" ||
    type === "integer" ||
    type === "boolean"
  )
    return true;
  if (type === "object") {
    const properties = objectSchema(schema.properties);
    if (!properties) return false;
    return Object.values(properties).every((item) => {
      const child = objectSchema(item);
      return child !== null && supported(child);
    });
  }
  if (type === "array") {
    const items = objectSchema(schema.items);
    return items !== null && supported(items);
  }
  return false;
}

function defaultValue(schema: JsonSchema): unknown {
  if ("const" in schema) return schema.const;
  if ("default" in schema) return schema.default;
  if (Array.isArray(schema.enum)) return schema.enum[0];
  const type = schemaType(schema);
  if (type === "object") {
    const properties = objectSchema(schema.properties) ?? {};
    return Object.fromEntries(
      Object.entries(properties).flatMap(([key, item]) => {
        const child = objectSchema(item);
        return child ? [[key, defaultValue(child)]] : [];
      }),
    );
  }
  if (type === "array") {
    const items = objectSchema(schema.items);
    const count = typeof schema.minItems === "number" ? schema.minItems : 0;
    return Array.from({ length: Math.min(count, 10) }, () =>
      items ? defaultValue(items) : null,
    );
  }
  if (type === "boolean") return false;
  if (type === "number" || type === "integer") return schema.minimum ?? 0;
  return "";
}

export function supportsSchemaInputs(schema: JsonSchema): boolean {
  return schemaType(schema) === "object" && supported(schema);
}

export function validateSchemaInputs(
  schema: JsonSchema,
  value: InputValues,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const validate = (current: JsonSchema, actual: unknown, path: string) => {
    const type = schemaType(current);
    if (type === "object") {
      if (!actual || typeof actual !== "object" || Array.isArray(actual)) {
        errors[path || "inputs"] = "Enter an object of Function inputs.";
        return;
      }
      const object = actual as Record<string, unknown>;
      const properties = objectSchema(current.properties) ?? {};
      const required = Array.isArray(current.required) ? current.required : [];
      for (const [name, item] of Object.entries(properties)) {
        const child = objectSchema(item);
        if (!child) continue;
        const childPath = path ? `${path}.${name}` : name;
        if (
          required.includes(name) &&
          (object[name] === undefined || object[name] === "")
        ) {
          errors[childPath] = "This field is required.";
        } else if (object[name] !== undefined) {
          validate(child, object[name], childPath);
        }
      }
      return;
    }
    if (type === "array") {
      if (!Array.isArray(actual)) {
        errors[path] = "Enter a list of values.";
        return;
      }
      if (
        typeof current.minItems === "number" &&
        actual.length < current.minItems
      ) {
        errors[path] =
          `Add at least ${current.minItems} item${current.minItems === 1 ? "" : "s"}.`;
      }
      const itemSchema = objectSchema(current.items);
      if (itemSchema)
        actual.forEach((item, index) =>
          validate(itemSchema, item, `${path}[${index + 1}]`),
        );
      return;
    }
    if (type === "number" || type === "integer") {
      if (typeof actual !== "number" || !Number.isFinite(actual)) {
        errors[path] = "Enter a number.";
      } else if (type === "integer" && !Number.isInteger(actual)) {
        errors[path] = "Enter a whole number.";
      } else if (
        typeof current.minimum === "number" &&
        actual < current.minimum
      ) {
        errors[path] = `Use ${current.minimum} or more.`;
      } else if (
        typeof current.maximum === "number" &&
        actual > current.maximum
      ) {
        errors[path] = `Use ${current.maximum} or less.`;
      }
    } else if (type === "string") {
      if (typeof actual !== "string") errors[path] = "Enter text.";
      else if (
        typeof current.minLength === "number" &&
        actual.length < current.minLength
      ) {
        errors[path] = `Enter at least ${current.minLength} characters.`;
      }
    } else if (type === "boolean" && typeof actual !== "boolean") {
      errors[path] = "Choose true or false.";
    }
  };
  validate(schema, value, "");
  return errors;
}

function writePath(
  value: unknown,
  path: Array<string | number>,
  next: unknown,
): unknown {
  if (path.length === 0) return next;
  const [part, ...rest] = path;
  if (typeof part === "number") {
    const list = Array.isArray(value) ? [...value] : [];
    list[part] = writePath(list[part], rest, next);
    return list;
  }
  const object =
    value && typeof value === "object" && !Array.isArray(value)
      ? { ...(value as Record<string, unknown>) }
      : {};
  object[part] = writePath(object[part], rest, next);
  return object;
}

export function SchemaInputFields({
  schema,
  value,
  errors,
  disabled = false,
  onChange,
}: {
  schema: JsonSchema;
  value: InputValues;
  errors: Record<string, string>;
  disabled?: boolean;
  onChange: (value: InputValues) => void;
}) {
  const rootProperties = objectSchema(schema.properties) ?? {};
  const rootRequired = Array.isArray(schema.required) ? schema.required : [];

  function renderField(
    name: string,
    currentSchema: JsonSchema,
    current: unknown,
    path: Array<string | number>,
    required: boolean,
    errorPath: string,
    isDisabled: boolean,
  ): ReactNode {
    const type = schemaType(currentSchema);
    const description =
      typeof currentSchema.description === "string"
        ? currentSchema.description
        : null;
    const update = (next: unknown) =>
      onChange(writePath(value, path, next) as InputValues);
    const error = errors[errorPath];
    if (type === "object") {
      const properties = objectSchema(currentSchema.properties) ?? {};
      const object =
        current && typeof current === "object" && !Array.isArray(current)
          ? (current as Record<string, unknown>)
          : {};
      const requiredFields = Array.isArray(currentSchema.required)
        ? currentSchema.required
        : [];
      return (
        <fieldset className={styles.schemaGroup} key={errorPath || name}>
          <legend>{name}</legend>
          {description ? <p>{description}</p> : null}
          {Object.entries(properties).map(([key, rawChild]) => {
            const child = objectSchema(rawChild);
            return child
              ? renderField(
                  key,
                  child,
                  object[key],
                  [...path, key],
                  requiredFields.includes(key),
                  `${errorPath ? `${errorPath}.` : ""}${key}`,
                  isDisabled,
                )
              : null;
          })}
        </fieldset>
      );
    }
    if (type === "array") {
      const itemSchema = objectSchema(currentSchema.items);
      const items = Array.isArray(current) ? current : [];
      if (!itemSchema) return null;
      return (
        <fieldset className={styles.schemaGroup} key={errorPath || name}>
          <legend>
            {name}
            {required ? " · required" : ""}
          </legend>
          {description ? <p>{description}</p> : null}
          {error ? <p className={styles.fieldError}>{error}</p> : null}
          {items.map((item, index) => (
            <div className={styles.schemaArrayItem} key={index}>
              {renderField(
                `Item ${index + 1}`,
                itemSchema,
                item,
                [...path, index],
                true,
                `${errorPath}[${index + 1}]`,
                isDisabled,
              )}
              <button
                type="button"
                disabled={isDisabled}
                onClick={() =>
                  update(items.filter((_, itemIndex) => itemIndex !== index))
                }
              >
                Remove item {index + 1}
              </button>
            </div>
          ))}
          <button
            type="button"
            disabled={isDisabled}
            onClick={() => update([...items, defaultValue(itemSchema)])}
          >
            Add item
          </button>
        </fieldset>
      );
    }
    const choices = Array.isArray(currentSchema.enum)
      ? currentSchema.enum
      : null;
    const label = `${name}${required ? " · required" : ""}`;
    const describedBy =
      [
        description ? `${errorPath}-description` : null,
        error ? `${errorPath}-error` : null,
      ]
        .filter(Boolean)
        .join(" ") || undefined;
    return (
      <Field label={label} key={errorPath || name}>
        {choices ? (
          <select
            disabled={isDisabled}
            aria-describedby={describedBy}
            value={JSON.stringify(current ?? choices[0])}
            onChange={(event) => update(JSON.parse(event.target.value))}
          >
            {choices.map((choice) => (
              <option
                key={JSON.stringify(choice)}
                value={JSON.stringify(choice)}
              >
                {String(choice)}
              </option>
            ))}
          </select>
        ) : type === "boolean" ? (
          <input
            disabled={isDisabled}
            aria-describedby={describedBy}
            type="checkbox"
            checked={current === true}
            onChange={(event) => update(event.target.checked)}
          />
        ) : (
          <input
            disabled={isDisabled}
            aria-describedby={describedBy}
            type={type === "number" || type === "integer" ? "number" : "text"}
            step={
              type === "integer" ? "1" : type === "number" ? "any" : undefined
            }
            min={
              typeof currentSchema.minimum === "number"
                ? currentSchema.minimum
                : undefined
            }
            max={
              typeof currentSchema.maximum === "number"
                ? currentSchema.maximum
                : undefined
            }
            value={
              current === undefined || current === null ? "" : String(current)
            }
            onChange={(event) =>
              update(
                type === "number" || type === "integer"
                  ? event.target.value === ""
                    ? undefined
                    : Number(event.target.value)
                  : event.target.value,
              )
            }
          />
        )}
        {description ? (
          <span id={`${errorPath}-description`}>{description}</span>
        ) : null}
        {error ? (
          <span
            id={`${errorPath}-error`}
            className={styles.fieldError}
            role="alert"
          >
            {error}
          </span>
        ) : null}
      </Field>
    );
  }

  return (
    <div className={styles.schemaInputFields}>
      {Object.entries(rootProperties).map(([name, rawChild]) => {
        const child = objectSchema(rawChild);
        return child
          ? renderField(
              name,
              child,
              value[name],
              [name],
              rootRequired.includes(name),
              name,
              disabled,
            )
          : null;
      })}
    </div>
  );
}
