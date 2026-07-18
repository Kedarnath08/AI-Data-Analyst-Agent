from pypdf import PdfReader

def extract_text_from_pdf(path: str):
    """
    Extracts text from each page of a PDF, preserving page numbers.
    Returns a list of dicts: [{"text": ..., "page": ...}, ...]
    Page numbers start from 1.
    """
    pages = []
    with open(path, "rb") as f:
        reader = PdfReader(f)
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            pages.append({
                "text": page_text or "",
                "page": i + 1  # 1-based page numbers
            })
    return pages