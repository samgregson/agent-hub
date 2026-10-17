export interface ImageOutput {
  kind: "image";
  mimeType: "image/png";
  dataBase64: string;
  altText: string;
}

export function isImageOutput(value: unknown): value is ImageOutput {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const image = value as Record<string, unknown>;
  return (
    image.kind === "image" &&
    image.mimeType === "image/png" &&
    typeof image.dataBase64 === "string" &&
    image.dataBase64.length > 0 &&
    image.dataBase64.length <= 120_000 &&
    /^[A-Za-z0-9+/]+={0,2}$/.test(image.dataBase64) &&
    typeof image.altText === "string" &&
    image.altText.length <= 500
  );
}

export function imageDataUrl(image: ImageOutput): string {
  return `data:image/png;base64,${image.dataBase64}`;
}
