# csv-schema-inferer

Analyzes a CSV string and infers column data types (`int`, `float`, `date`, `bool`, `string`) by sampling rows from the start of the file.

```python
from csv_schema_inferer import infer_schema

schema = infer_schema("name,age,active\nAlice,30,true\nBob,25,false")
# {'name': 'string', 'age': 'int', 'active': 'bool'}
```

The library exports three names: `infer_schema(csv_text, delimiter=",", sample_size=1000)`, which returns a `dict[str, str]` mapping header to type; `infer_column_type(values)`, which classifies a single list of string values; and `detect_columns(rows)`, which splits a list of rows into headers and aligned data rows.

## Why this exists

When you load a CSV into a database or a typed dataframe, you need to know column types before you can create the target schema. This library answers that question using only the Python standard library — no pandas, no numpy, no network access. The trade-off is speed and simplicity over statistical inference: we classify each value against a fixed set of patterns and reduce to the most general type that fits all sampled values. This is fast and deterministic, but it will not detect formats outside the supported set (e.g., US-style `MM/DD/YYYY` dates are classified as `string`, not `date`).

## Edge cases you will hit

- **Sampling is from the top of the file, not random.** If row 5000 introduces a float in an otherwise-integer column, and your `sample_size` is 1000, the column will be inferred as `int`. This is deliberate — random sampling would make the function non-deterministic.
- **Duplicate header names** collapse into a single dict key; the last column with that name wins.
- **Dates** must be ISO 8601 (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`). Invalid calendar dates like `2024-13-01` are classified as `string`, not `date`.
- **Empty values** (empty string or whitespace-only) are treated as nulls and do not influence the inferred type. A column of entirely empty values defaults to `string`.
- **`nan`, `inf`, `-inf`** are classified as `float`, matching Python's `float()` constructor.
