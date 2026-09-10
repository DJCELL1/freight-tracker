"""Turn a freight PDF into per-page text, whether it is born-digital or a scan.

The manifests that come off the despatch scanner have no text layer at all, so
a plain text extract hands back a stack of empty pages. When that happens we
rasterise the pages and OCR them instead.

The OCR settings are not arbitrary. The manifest number and the column headings
are printed light-grey on grey, and only come through legibly at 400 DPI with
the contrast stretched and Tesseract held in "uniform block of text" mode
(--psm 6). Dropping to the defaults loses the manifest number entirely.
"""

import io

DPI = 400
TESSERACT_CONFIG = "--psm 6"

# A page with fewer characters than this is treated as having no text layer.
# Scanned pages usually extract as "" but can pick up a stray ligature or two.
MIN_TEXT_LAYER_CHARS = 30


class PdfReadError(Exception):
    pass


def _as_bytes(pdf) -> bytes:
    """Accept a path, raw bytes, or a Streamlit UploadedFile / file object."""
    if isinstance(pdf, bytes):
        return pdf
    if isinstance(pdf, str):
        with open(pdf, "rb") as fh:
            return fh.read()
    if hasattr(pdf, "read"):
        if hasattr(pdf, "seek"):
            pdf.seek(0)
        return pdf.read()
    raise PdfReadError(f"Don't know how to read a PDF from {type(pdf).__name__}")


def _text_layer(data: bytes) -> list:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def _ocr(data: bytes) -> list:
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        from PIL import ImageOps
    except ImportError as e:  # pragma: no cover - depends on the host install
        raise PdfReadError(
            "This PDF is a scan with no text layer, so it needs OCR. Install the "
            "OCR extras: `pip install pytesseract pdf2image pillow` plus the "
            "system packages `tesseract-ocr` and `poppler-utils`."
        ) from e

    try:
        images = convert_from_bytes(data, dpi=DPI)
    except Exception as e:  # pdf2image raises its own family of errors
        raise PdfReadError(f"Could not rasterise the PDF for OCR: {e}") from e

    texts = []
    for image in images:
        prepared = ImageOps.autocontrast(ImageOps.grayscale(image), cutoff=1)
        texts.append(pytesseract.image_to_string(prepared, config=TESSERACT_CONFIG))
    return texts


def extract_pages(pdf):
    """Returns (page_texts, ocr_used).

    Tries the text layer first because it is exact and instant; falls back to
    OCR only for the pages that come back blank.
    """
    data = _as_bytes(pdf)
    if not data:
        raise PdfReadError("The uploaded file is empty.")

    try:
        pages = _text_layer(data)
    except Exception as e:
        raise PdfReadError(f"Could not open the PDF: {e}") from e

    has_text = any(len(p.strip()) >= MIN_TEXT_LAYER_CHARS for p in pages)
    if has_text:
        return pages, False
    return _ocr(data), True
