import io
import fitz          
from docx import Document  


def extract_from_pdf(file_bytes: bytes) -> str:
    text = ""
    pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in pdf_doc:
        page_text = page.get_text()
        text += page_text + " "
    pdf_doc.close()
    return text.strip()


def extract_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    paragraphs = [
        para.text
        for para in doc.paragraphs
        if para.text.strip()   # skip empty paragraphs
    ]
    return " ".join(paragraphs)


def extract_from_txt(file_bytes: bytes) -> str:

    return file_bytes.decode('utf-8', errors='ignore')


def extract_text(file_bytes: bytes, filename: str) -> str:
    name_lower = filename.lower()

    if name_lower.endswith('.pdf'):
        return extract_from_pdf(file_bytes)

    elif name_lower.endswith('.docx'):
        return extract_from_docx(file_bytes)

    elif name_lower.endswith('.txt'):
        return extract_from_txt(file_bytes)

    else:
        # For ZIP or other formats, try plain text decode as fallback
        # In future: could unzip and extract text from inner files
        try:
            return file_bytes.decode('utf-8', errors='ignore')
        except Exception:
            return ""
