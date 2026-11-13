"""JSONC source projections retain syntax and keep entry comments attached."""

import unittest

import json5

from src.apps.jsonc import Document


class JSONCProjectionTests(unittest.TestCase):
    def test_crlf_bom_and_inline_comments_after_the_final_retained_entry(self):
        source = '\ufeff{\r\n  "keep": 1, // kept note\r\n  "remove": 2\r\n}\r\n'
        result = Document(source).project({"keep": 1}, lambda comment: True)
        self.assertEqual(json5.loads(result), {"keep": 1})
        self.assertIn("// kept note\r\n}", result)
        self.assertTrue(result.startswith("\ufeff{"))
        self.assertNotIn("\n", result.replace("\r\n", ""))

    def test_identity_and_comment_ownership_for_nested_and_escaped_values(self):
        source = """// Document header
{
  // Kept leading note
  "keep": {"url": "https://example.invalid/a,//b", /* nested */ "array": [1, 2,]}, // Kept tail

  /* Removed leading note */
  'remove': "value", /* Removed tail */
  unicodeKey: "a \\"quoted\\" value"
}
// Document footer
"""
        document = Document(source)
        self.assertEqual(document.project(document.value), source)
        chosen = {"keep": document.value["keep"], "unicodeKey": document.value["unicodeKey"]}
        result = document.project(chosen, lambda comment: True)
        self.assertEqual(json5.loads(result), chosen)
        for kept in (
            "// Kept leading note",
            "/* nested */",
            "// Kept tail",
            "https://example.invalid/a,//b",
        ):
            self.assertIn(kept, result)
        for removed in (
            "Removed leading note",
            "Removed tail",
            "Document header",
            "Document footer",
        ):
            self.assertNotIn(removed, result)

    def test_first_middle_last_and_all_entries_with_comma_conventions(self):
        for source in ('{"a":1,"b":2,"c":3}', '{"a":1,"b":2,"c":3,}', "[1,2,3]", "[1,2,3,]"):
            doc = Document(source)
            subsets = (
                [{"a": 1}, {"b": 2}, {"c": 3}, {}, {"a": 1, "c": 3}]
                if isinstance(doc.value, dict)
                else [[1], [2], [3], [], [1, 3]]
            )
            for selected in subsets:
                with self.subTest(source=source, selected=selected):
                    projected = doc.project(selected)
                    self.assertEqual(json5.loads(projected), selected)
                    if selected:
                        self.assertEqual(projected[-2] == ",", source[-2] == ",")

    def test_nested_regions_survive_only_where_entries_remain(self):
        source = """{
  // #region Outer
  // #region Inner
  "private": 1,
  "public": 2,
  // #endregion Inner
  // #region Empty
  "onlyPrivate": 3,
  // #endregion Empty
  // #endregion Outer
}
"""
        result = Document(source).project({"public": 2}, lambda comment: True)
        self.assertEqual(json5.loads(result), {"public": 2})
        self.assertEqual(result.count("// #region"), 2)
        self.assertEqual(result.count("// #endregion"), 2)
        self.assertNotIn("Empty", result)
        redacted = Document(source).project({"public": 2}, lambda c: "Inner" not in c)
        self.assertEqual(redacted.count("// #region"), 1)
        self.assertEqual(redacted.count("// #endregion"), 1)
        self.assertNotIn("Inner", redacted)
        nested = """{
  "keep": {
    // #region private-label
    "option": true
    // #endregion
  },
  "remove": 1
}"""
        document = Document(nested)
        redacted = document.project(
            {"keep": document.value["keep"]}, lambda comment: "private-label" not in comment
        )
        self.assertEqual(json5.loads(redacted), {"keep": {"option": True}})
        self.assertNotIn("#region", redacted)
        self.assertNotIn("#endregion", redacted)
