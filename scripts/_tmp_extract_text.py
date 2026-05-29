#!/usr/bin/env python3
import sys
import fitz

pdf_path = sys.argv[1]
out_path = sys.argv[2]
doc = fitz.open(pdf_path)
parts = []
for i, page in enumerate(doc):
    parts.append(f"\n\n===== PAGE {i+1} =====\n")
    parts.append(page.get_text("text"))
text = "".join(parts)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(text)
print(f"pages={doc.page_count} chars={len(text)}")
