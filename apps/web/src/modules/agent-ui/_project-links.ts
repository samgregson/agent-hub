export interface ProjectLinkSegment {
  label?: string;
  path?: string;
  text?: string;
}

export function parseProjectFileLinks(text: string): ProjectLinkSegment[] {
  const pattern = /\[([^\]]+)]\((\/project\/[^)\s]+)\)/g;
  const segments: ProjectLinkSegment[] = [];
  let start = 0;
  for (const match of text.matchAll(pattern)) {
    const index = match.index;
    const label = match[1];
    const path = match[2];
    if (
      index === undefined ||
      label === undefined ||
      path === undefined ||
      path.split("/").includes("..")
    ) {
      continue;
    }
    if (index > start) segments.push({ text: text.slice(start, index) });
    segments.push({ label, path });
    start = index + match[0].length;
  }
  if (start < text.length) segments.push({ text: text.slice(start) });
  return segments;
}
