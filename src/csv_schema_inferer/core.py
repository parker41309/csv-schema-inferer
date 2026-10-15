"""Core inference logic for CSV schema analysis.

Design decisions:
  * We parse with Python's stdlib `csv` module, which handles quoted fields
    correctly. We do not roll our own parser — edge cases in quoted fields
    are a source of bugs, and the stdlib parser is well-tested.
  * Type inference is row-by-row reduction: we start assuming each column is
    an int, and every value either confirms, widens, or invalidates that guess.
    This is simple and deterministic — no sampling randomness, no statistics.
  * We only inspect rows; we do not look at column names. Column names are
    metadata, not evidence of data type.
"""

import csv
import io
import re
from datetime import datetime
from typing import Dict, List, Tuple


# Order of strictness: if a value fails int, it might be float; if it fails
# float, it might be date; etc. `string` is the fallback.
# We try int first because every int literal is a valid float, but not
# vice versa — so int-then-float preserves the most specific type.
_TYPE_PRIORITY = ("int", "float", "date", "bool", "string")


# Precompiled patterns for performance and clarity.
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$|^[+-]?inf$|^[+-]?nan$",
    re.IGNORECASE,
)

# ISO 8601 date/datetime. We support the common forms rather than every
# exotic variant. Supporting every ISO 8601 edge case (week numbers,
# ordinal dates, time offsets) would make this pattern unmaintainable
# and the inference less useful — a column of `2024-W01-1` is rare enough
# that we'd rather call it string than misclassify half the time.
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2})?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$"
)


def _classify_value(value: str) -> str:
    """Classify a single string value into one of the supported types.

    Empty strings are treated as nulls and do not constrain the column
    type — they're missing data, not evidence. We return the sentinel
    "null" so the caller can skip them during reduction.
    """
    if value is None or value == "":
        return "null"
    v = value.strip()
    if v == "":
        return "null"
    lower = v.lower()
    if lower in ("true", "false"):
        return "bool"
    if _INT_RE.match(v):
        return "int"
    if _FLOAT_RE.match(v):
        return "float"
    if _DATE_RE.match(v):
        # Validate the date is real (e.g. reject 2024-13-45) by
        # attempting a parse. strptime is strict about ranges.
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
            return "date"
        except ValueError:
            pass
    return "string"


def _widen(current: str, candidate: str) -> str:
    """Reduce two type labels to the most general that covers both.

    This is the core of inference: if a column has been `int` and we see
    a `float`, the column is now `float`. If it's been `float` and we see
    `string`, it's now `string`. `null` never widens anything.
    """
    if candidate == "null":
        return current
    if current == "null":
        return candidate
    if current == candidate:
        return current
    # Pick the later type in the priority order — that's the more general one.
    idx = max(_TYPE_PRIORITY.index(current), _TYPE_PRIORITY.index(candidate))
    return _TYPE_PRIORITY[idx]


def detect_columns(rows: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
    """Split rows into (headers, data_rows).

    The first row is treated as headers. Subsequent rows are data.
    Rows shorter than the header row are padded with empty strings so
    every data row aligns with a column; this matches the behaviour of
    most spreadsheet tools when a row is missing trailing values.
    Rows longer than the header row are truncated — extra cells are
    dropped, because we have no column name to attach them to.
    """
    if not rows:
        return [], []
    headers = rows[0]
    width = len(headers)
    data = []
    for row in rows[1:]:
        if len(row) < width:
            row = row + [""] * (width - len(row))
        elif len(row) > width:
            row = row[:width]
        data.append(row)
    return headers, data


def infer_column_type(values: List[str]) -> str:
    """Infer the type of a single column from a list of string values.

    Reduces over all values; a column is only as specific as its most
    general non-null member. If every value is null, we return "string"
    — a column with no data has no type, and string is the safe default.
    """
    result = "null"
    for v in values:
        result = _widen(result, _classify_value(v))
    if result == "null":
        return "string"
    return result


def infer_schema(
    csv_text: str,
    delimiter: str = ",",
    sample_size: int = 1000,
) -> Dict[str, str]:
    """Infer column types for a CSV string.

    Args:
        csv_text: The full CSV content as a string.
        delimiter: Field delimiter. Defaults to comma.
        sample_size: Maximum number of data rows to inspect. Inference
            is done on a sample for speed on large files. The sample is
            the first `sample_size` data rows — not random. Random
            sampling would make the function non-deterministic, and
            determinism is a hard requirement of this library. The
            first N rows are a reasonable sample for most real-world
            CSVs where columns are homogeneous.

    Returns:
        A dict mapping column name (header) to inferred type string.
        Types are one of: int, float, date, bool, string.

    Edge cases:
        * Empty CSV text returns an empty dict.
        * CSV with only a header row returns {col: "string"} for each
          column, since no data means no evidence to narrow the type.
        * Quoted fields with commas are handled by the stdlib csv parser.
        * Leading/trailing whitespace in values is stripped before
          classification, because CSV exporters commonly pad fields.
    """
    if not csv_text:
        return {}
    # Use io.StringIO to feed the csv reader. newline="" is critical:
    # the csv module handles its own line endings, and letting Python
    # translate newlines first corrupts embedded newlines in quoted fields.
    reader = csv.reader(io.StringIO(csv_text, newline=""), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        if i == 0:
            rows.append(row)
            continue
        rows.append(row)
        if len(rows) - 1 >= sample_size:
            break
    headers, data = detect_columns(rows)
    if not headers:
        return {}
    result: Dict[str, str] = {}
    for col_idx, header in enumerate(headers):
        col_values = [row[col_idx] for row in data if col_idx < len(row)]
        result[header] = infer_column_type(col_values)
    return result
