---
status: accepted
---

# Ingest documents as Project-owned sources and searchable virtual files

Project Files owns uploaded PDF/DOCX originals, their immutable source hash and
version, conversion metadata, and generated text. A document is reusable Project
source material, not automatically an Artifact. No MCP server or external index
owns document state.

Keep the exact uploaded bytes in `project_documents`, keyed by Project and
host-issued document ID. In the same transaction, register protected text files
under `/project/.documents/<id>/`: `manifest.json`, `text.md`, and PDF
`pages/NNN.md`. The manifest is a generated projection of the upload metadata;
the original bytes remain authoritative. Reconstructing application adapters
must preserve both original bytes and searchable text. Uploading the same filename
again creates a new source identity; replacement/re-ingestion is not implicit.

Use pinned MarkItDown conversion, splitting PDFs before extraction to retain page
boundaries. DOCX has no stable pagination. Original PDF pages render on demand
through PDFium for both the Library viewer and a read-only multimodal agent tool.
Empty extraction is explicitly flagged as needing OCR/inspection; no automatic
OCR or claim of complete visual extraction is made. Rendering a page does not
write a file, modify an upload, or create an Artifact.

The normal Deep Agents filesystem reads, glob and grep already cover the generated
Markdown. Add bounded document discovery and page-image inspection tools, not a
second search engine or unconditional document injection into prompts. Native PTC
may discover documents and read their text through its existing read capabilities;
image inspection remains an ordinary multimodal tool. Document content cannot
override host instructions or approval policy.

Uploads and document deletion are explicit user actions. Generic file writes,
edits and deletion reject `/.documents` paths so source text cannot silently be
changed independently of the original. Explicit document deletion removes original
and generated files together. PDF/DOCX conversion runs in a separate process with
time, address-space, input, page, output and expanded-archive bounds. The initial
limits are 10 MB uploads, 100 PDF pages, 800 KB extracted text, 30 MB expanded DOCX,
and two concurrent conversion/render jobs per API process.

Library shows one document entry, with rendered original pages, page/zoom controls,
extracted Markdown, warnings and original download. DOCX supports extracted text
and original download; it does not invent a Word pagination or render its embedded
images separately. No Plugin code is imported into the host, and no new app-specific
behavior is added to the generic MCP App host.
