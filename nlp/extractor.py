import io
import logging
import zipfile

import fitz          
from docx import Document  
from embeddings.chunking import MAX_DOCUMENT_CHARACTERS, MAX_DOCUMENT_LINES

logger = logging.getLogger(__name__)


SUPPORTED_DOCUMENT_TYPES = {
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".txt": "TXT",
}


class DocumentValidationError(ValueError):
    """An uploaded document is unsupported or does not match its file type."""


class DocumentExtractionError(ValueError):
    """A supported document could not be read or contains no usable text."""


class DocumentLimitError(ValueError):
    """Extracted document content exceeded the processing limits."""


def _check_extracted_limits(characters: int, lines: int) -> None:
    if characters > MAX_DOCUMENT_CHARACTERS:
        raise DocumentLimitError(
            f"Extracted document text exceeds the {MAX_DOCUMENT_CHARACTERS:,}-character limit. "
            "Shorten the document and try again."
        )
    if lines > MAX_DOCUMENT_LINES:
        raise DocumentLimitError(
            f"Extracted document text exceeds the {MAX_DOCUMENT_LINES:,}-line limit. "
            "Shorten the document and try again."
        )


def validate_document(file_bytes: bytes, filename: str) -> str:
    """Validate document content using signatures, not browser-supplied MIME types."""
    extension = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in SUPPORTED_DOCUMENT_TYPES:
        raise DocumentValidationError("Unsupported file type. Upload a PDF, DOCX, or TXT file.")
    if not file_bytes:
        raise DocumentValidationError("The uploaded file is empty.")

    if extension == ".pdf":
        # PDF headers can follow a short preamble, so look near the start of the file.
        if b"%PDF-" not in file_bytes[:1024]:
            raise DocumentValidationError("The file content does not match a PDF document.")
    elif extension == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                    raise DocumentValidationError("The file content does not match a DOCX document.")
                if archive.testzip() is not None:
                    raise DocumentValidationError("The DOCX file is damaged or invalid.")
        except zipfile.BadZipFile as exc:
            raise DocumentValidationError("The file content does not match a DOCX document.") from exc
    else:
        try:
            file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentValidationError("The TXT file must use UTF-8 text encoding.") from exc

    return extension


def extract_from_pdf(file_bytes: bytes) -> str:
    try:
        with fitz.open(stream=file_bytes, filetype="pdf") as pdf_doc:
            if pdf_doc.is_encrypted:
                raise DocumentExtractionError(
                    "This PDF is password-protected and cannot be read. Upload an unlocked PDF."
                )
            page_texts = []
            characters = 0
            lines = 0
            for page in pdf_doc:
                page_text = page.get_text()
                page_texts.append(page_text)
                characters += len(page_text) + (1 if len(page_texts) > 1 else 0)
                lines += len(page_text.splitlines())
                _check_extracted_limits(characters, lines)
            text = " ".join(page_texts).strip()
    except DocumentExtractionError:
        raise
    except DocumentLimitError:
        raise
    except (fitz.FileDataError, fitz.EmptyFileError, RuntimeError, ValueError) as exc:
        raise DocumentExtractionError(
            "This PDF is invalid or unreadable. Try exporting it again and re-uploading it."
        ) from exc

    if not text:
        raise DocumentExtractionError(
            "No selectable text could be extracted from this PDF. It may be a scanned document; "
            "scanned PDFs need OCR, which is not currently supported."
        )
    return text


def extract_from_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = []
        characters = 0
        lines = 0
        for para in doc.paragraphs:
            paragraph = para.text.strip()
            if not paragraph:
                continue
            paragraphs.append(paragraph)
            characters += len(paragraph) + (1 if len(paragraphs) > 1 else 0)
            lines += len(paragraph.splitlines())
            _check_extracted_limits(characters, lines)
        text = " ".join(paragraphs)
    except DocumentLimitError:
        raise
    except Exception as exc:  # Parser exceptions vary across python-docx/lxml versions.
        logger.warning("DOCX extraction failed (%s)", type(exc).__name__)
        raise DocumentExtractionError(
            "This DOCX file is invalid or unreadable. Try saving it again and re-uploading it."
        ) from exc

    if not text:
        raise DocumentExtractionError(
            "No text was found in this DOCX file. Add readable text and upload it again."
        )
    return text


def extract_from_txt(file_bytes: bytes) -> str:
    try:
        decoded = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        logger.warning("TXT decoding failed (%s)", type(exc).__name__)
        raise DocumentExtractionError(
            "This TXT file could not be read as UTF-8 text. Save it as UTF-8 and upload it again."
        ) from exc

    _check_extracted_limits(len(decoded), decoded.count("\n") + (1 if decoded else 0))
    text = decoded.strip()
    if not text:
        raise DocumentExtractionError(
            "No text was found in this TXT file. Add text and upload it again."
        )
    return text


def extract_text(file_bytes: bytes, filename: str) -> str:
    extension = validate_document(file_bytes, filename)

    if extension == '.pdf':
        return extract_from_pdf(file_bytes)
    elif extension == '.docx':
        return extract_from_docx(file_bytes)
    elif extension == '.txt':
        return extract_from_txt(file_bytes)
