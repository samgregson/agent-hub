# Document ingestion fixtures

These are generated, deliberately small documents containing no external data:

- `bridge.pdf`: two pages of selectable text and a blue vector rectangle. Page 1
  says “Bridge design: span 12.5 metres.”; page 2 contains a deflection criterion.
- `scan.pdf`: one page containing only a vector rectangle. It exercises empty
  text extraction and visual inspection without claiming automatic OCR.
- `criteria.docx`: a minimal Word document saying “Design criteria: imposed load
  3 kPa.” It exercises real MarkItDown/Mammoth conversion without pagination.

Project Files tests use real MarkItDown and PDFium. The agent-flow test uses a
scripted model with the real Deep Agents graph, grep/read tools and page-image
tool; it does not evaluate live language-model task quality. The browser test
uses the real migrated API, PostgreSQL and conversion worker with no document API
mocks. Set `AGENT_HUB_DOCUMENT_E2E=1` to enable it.
