from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import extract_images  # noqa: E402
import extract_references  # noqa: E402
import fetch_sources  # noqa: E402


class ExtractorTests(unittest.TestCase):
    def test_nested_bibtex_fields_are_structured(self):
        text = "@article{k, title={A {Nested} Title}, author={A and B}, year={2024}, doi={10.1/x}}"
        entry = extract_references.parse_bibtex(text, "fixture")[0]
        self.assertEqual(entry["title"], "A Nested Title")
        self.assertEqual(entry["doi"], "10.1/x")

    def test_payload_validation_rejects_html_as_pdf_and_bad_tar(self):
        with self.assertRaises(ValueError):
            fetch_sources.validate_payload("pdf", b"<html>not pdf</html>" * 100, "text/html")
        with self.assertRaises(ValueError):
            fetch_sources.validate_payload("tar", b"not a tar archive" * 100)

    def test_payload_validation_accepts_real_tar(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = b"hello"
            info = tarfile.TarInfo("main.tex")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        fetch_sources.validate_payload("tar", buffer.getvalue())

    def test_overpic_parsing_and_rendering(self):
        block = r"""
        \includegraphics{plain.pdf}
        \begin{overpic}{overlay.pdf}
          \put(10,20){\scriptsize Label}
          \put(70,80){\textcolor{green}{\cmark}}
        \end{overpic}
        """
        events = extract_images.parse_graphics_events(block)
        self.assertEqual([event["target"] for event in events], ["plain.pdf", "overlay.pdf"])
        self.assertEqual([item["text"] for item in events[1]["overlays"]], ["Label", "✓"])
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.pdf"
            target = Path(temporary) / "target.png"
            document = fitz.open()
            document.new_page(width=120, height=80)
            document.save(source)
            document.close()
            ok, mode, warnings = extract_images.convert_to_png(source, target, events[1]["overlays"])
            self.assertTrue(ok)
            self.assertEqual(mode, "pdf_rendered_with_overpic_overlay")
            self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
