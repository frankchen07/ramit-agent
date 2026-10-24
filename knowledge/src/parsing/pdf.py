"""PDF parser using pymupdf4llm."""
from pathlib import Path

from src.parsing.md import _extract_structure


def parse(filepath: Path) -> dict:
    try:
        import pymupdf4llm
    except ImportError:
        raise RuntimeError("pymupdf4llm not installed. Run: pip install pymupdf4llm")

    md_text = pymupdf4llm.to_markdown(str(filepath))
    return {
        "text": md_text,
        "media_type": "pdf",
        "structure": _extract_structure(md_text),
    }

