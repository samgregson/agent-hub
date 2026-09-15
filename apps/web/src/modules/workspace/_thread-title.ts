const maximumTitleLength = 60;

export function initialThreadTitle(index: number): string {
  return `New Thread ${index}`;
}

export function automaticThreadTitle(message: string): string | null {
  const normalized = message.replace(/\s+/g, " ").trim();
  if (!normalized) return null;
  if (normalized.length <= maximumTitleLength) return normalized;
  return `${normalized.slice(0, maximumTitleLength - 1).trimEnd()}…`;
}

export function hasProvisionalThreadTitle(title: string): boolean {
  return /^New Thread \d+$/.test(title);
}
