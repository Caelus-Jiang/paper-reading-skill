#!/usr/bin/env python3
import sys, json
import fitz

pdf_path = sys.argv[1]
out_dir = sys.argv[2]
doc = fitz.open(pdf_path)
manifest = []
seen = set()
idx = 1
for pno, page in enumerate(doc):
    imgs = page.get_images(full=True)
    for img in imgs:
        xref = img[0]
        if xref in seen:
            continue
        seen.add(xref)
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                pix = fitz.Pixmap(fitz.csRGB, pix)
            w, h = pix.width, pix.height
            if w < 80 or h < 80:
                continue
            out = f"{out_dir}/img_p{pno+1}_x{xref}.png"
            pix.save(out)
            manifest.append({"index": idx, "page": pno+1, "xref": xref, "w": w, "h": h, "file": out})
            idx += 1
        except Exception as e:
            print("err", xref, e)
print(json.dumps(manifest, indent=2))
