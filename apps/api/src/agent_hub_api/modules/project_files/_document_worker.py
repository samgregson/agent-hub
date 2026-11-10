"""Bounded local document conversion worker. No plugins or model credentials."""

import base64
import io
import json
import resource
import sys
import zipfile
from importlib.metadata import version
from typing import Any


def process(request: dict[str, Any]) -> dict[str, Any]:
    import pypdfium2 as pdfium  # type: ignore[import-untyped]
    from markitdown import MarkItDown
    from pypdf import PdfReader, PdfWriter

    source = base64.b64decode(request["source"], validate=True)
    extension = request["extension"]
    if extension == ".pdf":
        reader = PdfReader(io.BytesIO(source))
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs must be decrypted before upload.")
        count = len(reader.pages)
        if not 1 <= count <= 100:
            raise ValueError("PDFs must contain 1–100 pages.")
        if request["action"] == "render":
            index = request["page"] - 1
            if not 0 <= index < count:
                raise ValueError("Page is outside this PDF.")
            with pdfium.PdfDocument(source) as document:
                page = document[index]
                width, height = page.get_size()
                scale = min(1.5, 1600 / max(width, height))
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG")
                bitmap.close()
                page.close()
            return {"image": base64.b64encode(output.getvalue()).decode()}
        converter = MarkItDown(enable_plugins=False)
        pages, warnings = [], []
        for index, page in enumerate(reader.pages):
            writer = PdfWriter()
            writer.add_page(page)
            stream = io.BytesIO()
            writer.write(stream)
            stream.seek(0)
            try:
                text = converter.convert_stream(stream, file_extension=".pdf").text_content.strip()
            except Exception:
                text = ""
                warnings.append(
                    f"Page {index + 1}: text conversion failed; inspect the original page."
                )
            if not text:
                warnings.append(
                    f"Page {index + 1}: no text extracted; OCR or visual inspection is needed."
                )
            pages.append(text)
    else:
        with zipfile.ZipFile(io.BytesIO(source)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(e.file_size for e in entries) > 30_000_000:
                raise ValueError("The expanded DOCX exceeds the document limit.")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("Expected a DOCX document.")
        text = (
            MarkItDown(enable_plugins=False)
            .convert_stream(io.BytesIO(source), file_extension=".docx")
            .text_content.strip()
        )
        pages = [text]
        warnings = [
            "DOCX has no stable page numbers. Check the original for layout and embedded images."
        ]
        if not text:
            warnings.append("No text extracted; inspect the original document.")
    if sum(len(p.encode()) for p in pages) > 800_000:
        raise ValueError("Extracted text exceeds 800000 bytes; split the document.")
    return {
        "pages": pages,
        "warnings": warnings,
        "converter": "markitdown:" + version("markitdown"),
    }


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (35, 35))
    resource.setrlimit(resource.RLIMIT_AS, (1_500_000_000, 1_500_000_000))
    try:
        request = json.loads(sys.stdin.buffer.read(14_000_001))
        print(json.dumps(process(request), allow_nan=False))
    except Exception as error:
        print(json.dumps({"error": str(error)[:500]}))
        sys.exit(1)
