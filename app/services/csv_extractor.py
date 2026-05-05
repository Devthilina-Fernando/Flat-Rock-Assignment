import io
from app.utils.logging_config import get_logger

logger = get_logger(__name__)


def extract_text_from_csv(file_bytes: bytes) -> str:
    """Convert a CSV to a readable key:value text block for the LLM."""
    try:
        import pandas as pd

        for encoding in ("utf-8", "latin-1", "cp1252"):
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            return ""

        lines: list[str] = [f"CSV Data ({len(df)} rows, {len(df.columns)} columns):"]
        lines.append(f"Columns: {', '.join(df.columns.tolist())}")
        lines.append("")

        for idx, row in df.iterrows():
            lines.append(f"--- Row {idx + 1} ---")
            for col in df.columns:
                val = row[col]
                if pd.notna(val):
                    lines.append(f"  {col}: {val}")

        result = "\n".join(lines)
        logger.info("CSV extracted", rows=len(df), chars=len(result))
        return result
    except Exception as e:
        logger.error("CSV extraction failed", error=str(e))
        return ""
