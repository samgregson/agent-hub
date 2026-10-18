import { isImageOutput, type ImageOutput } from "@/modules/media";

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
