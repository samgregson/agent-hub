import { Fragment, type ReactNode } from "react";

import styles from "./markdown.module.css";

export interface MarkdownLink {
  label: string;
  url: string;
}

interface ProseBlock {
  text: string;
  type: "prose";
}

interface CodeBlock {
  code: string;
  language: string | null;
  type: "code";
}

type MarkdownBlock = CodeBlock | ProseBlock;

export function parseMarkdownBlocks(text: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = [];
  const pattern = /```([^\n`]*)\n([\s\S]*?)```/g;
  let start = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? start;
    const prose = text.slice(start, index).trim();
    if (prose) blocks.push({ text: prose, type: "prose" });
    blocks.push({
      code: match[2] ?? "",
      language: match[1]?.trim() || null,
      type: "code",
    });
    start = index + match[0].length;
  }

  const prose = text.slice(start).trim();
  if (prose) blocks.push({ text: prose, type: "prose" });
  return blocks;
}

export function parseInlineMarkdown(
  text: string,
): Array<string | MarkdownLink> {
  const segments: Array<string | MarkdownLink> = [];
  const pattern = /\[([^\]]+)]\(([^)\s]+)\)/g;
  let start = 0;

  for (const match of text.matchAll(pattern)) {
    const index = match.index ?? start;
    if (index > start) segments.push(text.slice(start, index));
    segments.push({ label: match[1] ?? "", url: match[2] ?? "" });
    start = index + match[0].length;
  }
  if (start < text.length) segments.push(text.slice(start));
  return segments;
}

function isVirtualFile(url: string): boolean {
  return /^\/(?:project|scratch)\//.test(url) && !url.split("/").includes("..");
}

function safeExternalUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? url
      : null;
  } catch {
    return null;
  }
}

function InlineMarkdown({
  onOpenVirtualFile,
  text,
}: {
  onOpenVirtualFile?: (path: string) => void;
  text: string;
}) {
  const content: ReactNode[] = [];

  for (const [index, segment] of parseInlineMarkdown(text).entries()) {
    if (typeof segment === "string") {
      const codeSegments = segment.split(/(`[^`]+`|\*\*[^*]+\*\*)/g);
      content.push(
        <Fragment key={index}>
          {codeSegments.map((value, nestedIndex) => {
            if (value.startsWith("`") && value.endsWith("`")) {
              return <code key={nestedIndex}>{value.slice(1, -1)}</code>;
            }
            if (value.startsWith("**") && value.endsWith("**")) {
              return <strong key={nestedIndex}>{value.slice(2, -2)}</strong>;
            }
            return value;
          })}
        </Fragment>,
      );
    } else if (isVirtualFile(segment.url) && onOpenVirtualFile) {
      content.push(
        <button
          className={styles.linkButton}
          key={index}
          onClick={() => onOpenVirtualFile(segment.url)}
          type="button"
        >
          {segment.label}
        </button>,
      );
    } else if (safeExternalUrl(segment.url)) {
      content.push(
        <a href={segment.url} key={index} rel="noreferrer" target="_blank">
          {segment.label}
        </a>,
      );
    } else {
      content.push(`[${segment.label}](${segment.url})`);
    }
  }

  return content;
}

export function Markdown({
  onOpenVirtualFile,
  text,
}: {
  onOpenVirtualFile?: (path: string) => void;
  text: string;
}) {
  return (
    <div className={styles.markdown}>
      {parseMarkdownBlocks(text).map((block, index) => {
        if (block.type === "code") {
          return (
            <pre data-language={block.language ?? undefined} key={index}>
              <code>{block.code}</code>
            </pre>
          );
        }

        const lines = block.text.split("\n");
        if (lines.every((line) => /^[-*]\s+/.test(line))) {
          return (
            <ul key={index}>
              {lines.map((line, lineIndex) => (
                <li key={lineIndex}>
                  <InlineMarkdown
                    onOpenVirtualFile={onOpenVirtualFile}
                    text={line.replace(/^[-*]\s+/, "")}
                  />
                </li>
              ))}
            </ul>
          );
        }

        const heading = /^(#{1,3})\s+(.+)$/.exec(block.text);
        if (heading) {
          const level = heading[1]?.length ?? 1;
          const content = (
            <InlineMarkdown
              onOpenVirtualFile={onOpenVirtualFile}
              text={heading[2] ?? ""}
            />
          );
          if (level === 1) return <h1 key={index}>{content}</h1>;
          if (level === 2) return <h2 key={index}>{content}</h2>;
          return <h3 key={index}>{content}</h3>;
        }

        return (
          <p key={index}>
            {lines.map((line, lineIndex) => (
              <Fragment key={lineIndex}>
                {lineIndex > 0 ? <br /> : null}
                <InlineMarkdown
                  onOpenVirtualFile={onOpenVirtualFile}
                  text={line}
                />
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
