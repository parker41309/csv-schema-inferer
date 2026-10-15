import unittest

from csv_schema_inferer import infer_schema, infer_column_type, detect_columns


class TestClassifyValue(unittest.TestCase):
    """Tests for single-value classification via infer_column_type."""

    def test_all_ints(self):
        self.assertEqual(infer_column_type(["1", "2", "3"]), "int")

    def test_int_with_negative(self):
        self.assertEqual(infer_column_type(["0", "-5", "42"]), "int")

    def test_int_widens_to_float(self):
        self.assertEqual(infer_column_type(["1", "2.5", "3"]), "float")

    def test_float_with_exponent(self):
        self.assertEqual(infer_column_type(["1.5e3", "2.0"]), "float")

    def test_float_with_leading_dot(self):
        self.assertEqual(infer_column_type([".5", ".25"]), "float")

    def test_bool_recognized(self):
        self.assertEqual(infer_column_type(["true", "false", "true"]), "bool")

    def test_bool_mixed_case(self):
        self.assertEqual(infer_column_type(["True", "FALSE"]), "bool")

    def test_date_iso(self):
        self.assertEqual(infer_column_type(["2024-01-15", "2023-12-01"]), "date")

    def test_date_with_time(self):
        self.assertEqual(
            infer_column_type(["2024-01-15T10:30:00", "2024-01-15T11:00:00"]),
            "date",
        )

    def test_invalid_date_rejected(self):
        # 2024-13-01 is month 13 — not a real date, should fall to string.
        self.assertEqual(infer_column_type(["2024-13-01"]), "string")

    def test_empty_values_are_null(self):
        # Nulls should not widen the type.
        self.assertEqual(infer_column_type(["1", "", "3"]), "int")

    def test_all_null_falls_to_string(self):
        self.assertEqual(infer_column_type(["", "", ""]), "string")

    def test_string_fallback(self):
        self.assertEqual(infer_column_type(["hello", "world"]), "string")

    def test_int_then_string_is_string(self):
        self.assertEqual(infer_column_type(["1", "abc"]), "string")

    def test_whitespace_stripped(self):
        # Exporters often pad fields; we strip before classifying.
        self.assertEqual(infer_column_type(["  42  ", "  7"]), "int")

    def test_nan_and_inf_are_float(self):
        self.assertEqual(infer_column_type(["nan", "inf", "-inf"]), "float")


class TestDetectColumns(unittest.TestCase):
    """Tests for header/data splitting and row alignment."""

    def test_basic_split(self):
        rows = [["a", "b"], ["1", "2"], ["3", "4"]]
        headers, data = detect_columns(rows)
        self.assertEqual(headers, ["a", "b"])
        self.assertEqual(data, [["1", "2"], ["3", "4"]])

    def test_short_row_padded(self):
        rows = [["a", "b", "c"], ["1", "2"]]
        headers, data = detect_columns(rows)
        self.assertEqual(data, [["1", "2", ""]])

    def test_long_row_truncated(self):
        rows = [["a", "b"], ["1", "2", "3", "4"]]
        headers, data = detect_columns(rows)
        self.assertEqual(data, [["1", "2"]])

    def test_empty_rows(self):
        headers, data = detect_columns([])
        self.assertEqual(headers, [])
        self.assertEqual(data, [])

    def test_header_only(self):
        rows = [["a", "b"]]
        headers, data = detect_columns(rows)
        self.assertEqual(headers, ["a", "b"])
        self.assertEqual(data, [])


class TestInferSchema(unittest.TestCase):
    """Tests for full CSV string inference."""

    def test_basic_csv(self):
        csv_text = "name,age,active\nAlice,30,true\nBob,25,false"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"name": "string", "age": "int", "active": "bool"})

    def test_quoted_fields_with_commas(self):
        csv_text = 'name,note\n"Alice, Jr",hello\n"Bob, Sr",world'
        result = infer_schema(csv_text)
        self.assertEqual(result, {"name": "string", "note": "string"})

    def test_empty_csv(self):
        self.assertEqual(infer_schema(""), {})

    def test_header_only(self):
        csv_text = "a,b,c"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"a": "string", "b": "string", "c": "string"})

    def test_semicolon_delimiter(self):
        csv_text = "a;b\n1;2.5"
        result = infer_schema(csv_text, delimiter=";")
        self.assertEqual(result, {"a": "int", "b": "float"})

    def test_sample_size_limit(self):
        # Build a CSV where the first 1000 rows are int, then a float appears.
        lines = ["col"]
        lines.extend([str(i) for i in range(1000)])
        lines.append("1.5")
        csv_text = "\n".join(lines)
        result = infer_schema(csv_text, sample_size=1000)
        # The float row is row 1001 (index 1000 in data), beyond the sample.
        self.assertEqual(result, {"col": "int"})

    def test_sample_size_includes_float(self):
        lines = ["col"]
        lines.extend([str(i) for i in range(999)])
        lines.append("1.5")
        csv_text = "\n".join(lines)
        result = infer_schema(csv_text, sample_size=1000)
        # The float is within the first 1000 data rows.
        self.assertEqual(result, {"col": "float"})

    def test_mixed_types_column(self):
        csv_text = "val\n1\n2.5\nhello\ntrue"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"val": "string"})

    def test_newline_in_quoted_field(self):
        # The csv module handles embedded newlines if newline="" is passed
        # to StringIO, which we do. This test verifies that.
        csv_text = 'a,b\n"line1\nline2",1\nx,2'
        result = infer_schema(csv_text)
        self.assertEqual(result, {"a": "string", "b": "int"})

    def test_date_column(self):
        csv_text = "d\n2024-01-01\n2024-02-01"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"d": "date"})

    def test_empty_values_in_int_column(self):
        csv_text = "n\n1\n\n3"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"n": "int"})

    def test_duplicate_headers(self):
        # Duplicate headers are preserved as-is; later values overwrite
        # earlier ones in the dict. This is a known limitation documented
        # in the README.
        csv_text = "a,a\n1,2"
        result = infer_schema(csv_text)
        self.assertEqual(result, {"a": "int"})


if __name__ == "__main__":
    unittest.main()
