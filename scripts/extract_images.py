#!/usr/bin/env python3
"""Extract author figures with TeX provenance and a validated PDF fallback."""

from __future__ import annotations

import argparse
import io
import re
import shutil
import tarfile
from pathlib import Path

import fitz
from PIL import Image, ImageColor, ImageDraw

from common import get_workspace, write_json


IMAGE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".eps"}
INCLUDE_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
SECTION_RE = re.compile(r"\\(section|subsection|subsubsection)\{([^{}]+)\}")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
FIGURE_RE = re.compile(r"\\begin\{(?:figure\*?|wrapfigure)\}(.+?)\\end\{(?:figure\*?|wrapfigure)\}", re.S)


def strip_tex_comments(text: str) -> str:
    output = []
    for line in text.splitlines():
        match = re.search(r"(?<!\\)%", line)
        output.append(line[: match.start()] if match else line)
    return "\n".join(output)


def find_matching_brace(text: str, opening: int) -> int | None:
    if opening >= len(text) or text[opening] != "{":
        return None
    depth = 0
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def extract_command_argument(text: str, command: str) -> str:
    match = re.search(rf"\\{re.escape(command)}\*?\s*(?:\[[^]]*\]\s*)?\{{", text)
    if not match:
        return ""
    opening = match.end() - 1
    closing = find_matching_brace(text, opening)
    return text[opening + 1:closing].strip() if closing is not None else ""


def clean_latex_text(text: str) -> str:
    text = text.replace("\\cmark", "✓").replace("\\xmark", "✗")
    text = re.sub(r"\\(?:scriptsize|footnotesize|small|normalsize|large)\b", "", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\\(?:textbf|textit|emph|mathrm|mathbf|bs)\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\textcolor\{[^{}]+\}\{([^{}]*)\}", r"\1", text)
        text = re.sub(r"\\rotatebox\{[^{}]+\}\{([^{}]*)\}", r"\1", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_put_overlays(text: str) -> list[dict]:
    overlays = []
    pattern = re.compile(r"\\put\s*\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)\s*\{")
    for match in pattern.finditer(text):
        opening = match.end() - 1
        closing = find_matching_brace(text, opening)
        if closing is None:
            continue
        raw = text[opening + 1:closing]
        rotation_match = re.search(r"\\rotatebox\{(-?\d+(?:\.\d+)?)\}", raw)
        color_match = re.search(r"\\textcolor\{([^{}]+)\}", raw)
        overlays.append(
            {
                "x": float(match.group(1)),
                "y": float(match.group(2)),
                "text": clean_latex_text(raw),
                "rotation": float(rotation_match.group(1)) if rotation_match else 0,
                "color_name": color_match.group(1) if color_match else "black",
            }
        )
    return overlays


def parse_graphics_events(block: str) -> list[dict]:
    events = []
    overpic_spans = []
    overpic_re = re.compile(
        r"\\begin\{overpic\}(?:\[[^]]*\])?\{([^}]+)\}(.+?)\\end\{overpic\}",
        re.S,
    )
    for match in overpic_re.finditer(block):
        events.append(
            {
                "position": match.start(),
                "target": match.group(1).strip(),
                "overlays": parse_put_overlays(match.group(2)),
                "graphics_kind": "overpic",
            }
        )
        overpic_spans.append((match.start(), match.end()))

    include_re = re.compile(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}")
    for match in include_re.finditer(block):
        if any(start <= match.start() < end for start, end in overpic_spans):
            continue
        events.append(
            {
                "position": match.start(),
                "target": match.group(1).strip(),
                "overlays": [],
                "graphics_kind": "includegraphics",
            }
        )
    events.sort(key=lambda item: item["position"])
    return events


def safe_extract_tar(source_tar: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source_tar, "r:*") as archive:
        safe_members = []
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                continue
            safe_members.append(member)
        try:
            archive.extractall(output_dir, members=safe_members, filter="data")
        except TypeError:
            archive.extractall(output_dir, members=safe_members)


def choose_main_tex(source_dir: Path) -> Path | None:
    scored = []
    for path in source_dir.rglob("*.tex"):
        text = strip_tex_comments(path.read_text(encoding="utf-8", errors="ignore"))
        score = 10 * int("\\documentclass" in text) + 5 * int("\\begin{document}" in text)
        score += len(INCLUDE_RE.findall(text))
        scored.append((score, path.stat().st_size, path))
    return max(scored, default=(0, 0, None), key=lambda item: (item[0], item[1]))[2]


def resolve_tex_include(base_tex: Path, source_dir: Path, target: str) -> Path | None:
    candidate = (base_tex.parent / target.strip()).resolve()
    if candidate.suffix.lower() != ".tex":
        candidate = candidate.with_suffix(".tex")
    try:
        candidate.relative_to(source_dir.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None


def expand_tex_tree(main_tex: Path, source_dir: Path) -> list[dict]:
    visited: set[Path] = set()
    segments: list[dict] = []

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visited or not path.exists():
            return
        visited.add(path)
        text = strip_tex_comments(path.read_text(encoding="utf-8", errors="ignore"))
        last = 0
        for match in INCLUDE_RE.finditer(text):
            if text[last:match.start()].strip():
                segments.append({"source_tex": path.relative_to(source_dir).as_posix(), "text": text[last:match.start()]})
            included = resolve_tex_include(path, source_dir, match.group(1))
            if included:
                visit(included)
            last = match.end()
        if text[last:].strip():
            segments.append({"source_tex": path.relative_to(source_dir).as_posix(), "text": text[last:]})

    visit(main_tex)
    return segments


def first_reference_context(full_text: str, label: str) -> str:
    if not label:
        return ""
    match = re.search(rf"\\(?:ref|autoref|cref|Cref)\{{{re.escape(label)}\}}", full_text)
    if not match:
        return ""
    snippet = full_text[max(0, match.start() - 180):match.end() + 180]
    return clean_latex_text(snippet)


def parse_tex_refs(segments: list[dict]) -> list[dict]:
    refs = []
    current_section = ""
    full_text = "\n".join(segment["text"] for segment in segments)
    for segment_order, segment in enumerate(segments, start=1):
        text = segment["text"]
        events = [("section", match.start(), match) for match in SECTION_RE.finditer(text)]
        events.extend(("figure", match.start(), match) for match in FIGURE_RE.finditer(text))
        events.sort(key=lambda item: item[1])
        for kind, _position, match in events:
            if kind == "section":
                current_section = clean_latex_text(match.group(2))
                continue
            block = match.group(1)
            caption = clean_latex_text(extract_command_argument(block, "caption"))
            label_match = LABEL_RE.search(block)
            label = label_match.group(1).strip() if label_match else ""
            for graphic in parse_graphics_events(block):
                target = graphic["target"].split(",", 1)[0].strip()
                refs.append(
                    {
                        "graphics_target": target,
                        "graphics_kind": graphic["graphics_kind"],
                        "overlays": graphic["overlays"],
                        "caption": caption,
                        "label": label,
                        "section_hint": current_section,
                        "first_reference_hint": first_reference_context(full_text, label),
                        "source_tex": segment["source_tex"],
                        "order": segment_order,
                    }
                )
    return refs


def build_image_index(source_dir: Path) -> list[Path]:
    return [path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]


def find_image(source_dir: Path, image_index: list[Path], target: str) -> Path | None:
    normalized_target = target.replace("\\", "/")
    target_stem = Path(normalized_target).stem
    candidates = []
    for path in image_index:
        relative = path.relative_to(source_dir).as_posix()
        if relative == normalized_target or str(Path(relative).with_suffix("")) == str(Path(normalized_target).with_suffix("")):
            candidates.append(path)
        elif path.stem == target_stem or relative.endswith(normalized_target):
            candidates.append(path)
    return min(candidates, default=None, key=lambda path: len(path.as_posix()))


def draw_overlays(path: Path, overlays: list[dict]) -> list[str]:
    warnings = []
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    draw = ImageDraw.Draw(image)
    for overlay in overlays:
        text = overlay.get("text", "")
        if not text:
            continue
        x = image.width * float(overlay.get("x", 0)) / 100
        y = image.height * (1 - float(overlay.get("y", 0)) / 100)
        try:
            color = ImageColor.getrgb(str(overlay.get("color_name") or "black"))
        except ValueError:
            color = (0, 0, 0)
            warnings.append(f"unknown overlay color: {overlay.get('color_name')}")
        rotation = float(overlay.get("rotation") or 0)
        if rotation:
            box = Image.new("RGBA", (max(20, len(text) * 12), 24), (255, 255, 255, 0))
            ImageDraw.Draw(box).text((0, 0), text, fill=color + (255,))
            box = box.rotate(rotation, expand=True)
            image.alpha_composite(box, (round(x), round(y)))
        else:
            draw.text((x, y), text, fill=color + (255,))
    image.convert("RGB").save(path, format="PNG")
    return warnings


def convert_to_png(source: Path, destination: Path, overlays: list[dict] | None = None) -> tuple[bool, str, list[str]]:
    overlays = overlays or []
    warnings: list[str] = []
    try:
        if source.suffix.lower() == ".pdf":
            with fitz.open(source) as document:
                if document.page_count == 0:
                    return False, "empty_pdf", ["PDF has no pages"]
                pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pixmap.save(destination)
            mode = "pdf_rendered"
        else:
            with Image.open(source) as image:
                image.convert("RGB").save(destination, format="PNG")
            mode = "image_converted"
        if overlays:
            warnings.extend(draw_overlays(destination, overlays))
            mode += "_with_overpic_overlay"
        with Image.open(destination) as check:
            check.verify()
        return True, mode, warnings
    except Exception as exc:  # noqa: BLE001 - conversion failures belong in the manifest
        destination.unlink(missing_ok=True)
        return False, f"conversion_failed:{source.suffix.lower()}", [str(exc)]


def extract_pdf_fallback(pdf_path: Path, images_dir: Path, start_index: int = 1) -> tuple[list[dict], list[str]]:
    figures = []
    warnings = []
    if not pdf_path.exists():
        return figures, ["paper.pdf unavailable for image fallback"]
    seen_xrefs = set()
    with fitz.open(pdf_path) as document:
        for page_number in range(document.page_count):
            page = document[page_number]
            for image_info in page.get_images(full=True):
                xref = image_info[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                try:
                    extracted = document.extract_image(xref)
                    content = extracted["image"]
                    with Image.open(io.BytesIO(content)) as image:
                        if image.width < 200 or image.height < 100:
                            continue
                        output = images_dir / f"figure_{start_index + len(figures):02d}.png"
                        image.convert("RGB").save(output, format="PNG")
                    figures.append(
                        {
                            "index": start_index + len(figures),
                            "original_file": f"paper.pdf#page={page_number + 1}:xref={xref}",
                            "saved_path": output.relative_to(images_dir.parent).as_posix(),
                            "source": "pdf_embedded_image",
                            "caption": "",
                            "label": "",
                            "section_hint": f"PDF page {page_number + 1}",
                            "first_reference_hint": "",
                            "conversion": "pdf_embedded_extracted",
                            "warnings": [],
                        }
                    )
                    if len(figures) >= 12:
                        return figures, warnings
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"xref {xref}: {exc}")

        if not figures:
            for page_number in range(min(document.page_count, 5)):
                output = images_dir / f"figure_{start_index + len(figures):02d}.png"
                pixmap = document[page_number].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                pixmap.save(output)
                figures.append(
                    {
                        "index": start_index + len(figures),
                        "original_file": f"paper.pdf#page={page_number + 1}",
                        "saved_path": output.relative_to(images_dir.parent).as_posix(),
                        "source": "pdf_page_fallback",
                        "caption": "PDF page fallback; crop to the actual figure before final delivery.",
                        "label": "",
                        "section_hint": f"PDF page {page_number + 1}",
                        "first_reference_hint": "",
                        "conversion": "pdf_page_rendered",
                        "warnings": ["whole-page fallback requires manual figure cropping"],
                    }
                )
    return figures, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--root", default="output")
    args = parser.parse_args()

    workspace, _ = get_workspace(Path(args.root).resolve(), args.input)
    raw_dir = workspace / "raw"
    cache_dir = workspace / "cache"
    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for stale in images_dir.glob("figure_*.png"):
        stale.unlink()

    source_tar = raw_dir / "source.tar"
    source_dir = cache_dir / "source_unpack"
    figures = []
    extraction_warnings = []
    if source_tar.exists():
        try:
            safe_extract_tar(source_tar, source_dir)
            main_tex = choose_main_tex(source_dir)
            segments = expand_tex_tree(main_tex, source_dir) if main_tex else []
            refs = parse_tex_refs(segments)
            image_index = build_image_index(source_dir)
            seen_targets = set()
            for ref in refs:
                target = ref["graphics_target"]
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                source_image = find_image(source_dir, image_index, target)
                if source_image is None:
                    extraction_warnings.append(f"source figure not found: {target}")
                    continue
                output = images_dir / f"figure_{len(figures) + 1:02d}.png"
                ok, mode, warnings = convert_to_png(source_image, output, ref.get("overlays"))
                if not ok:
                    extraction_warnings.extend(warnings)
                    continue
                figures.append(
                    {
                        "index": len(figures) + 1,
                        "original_file": source_image.relative_to(source_dir).as_posix(),
                        "saved_path": output.relative_to(workspace).as_posix(),
                        "source": "arxiv_source",
                        "graphics_target": target,
                        "graphics_kind": ref.get("graphics_kind", ""),
                        "caption": ref.get("caption", ""),
                        "label": ref.get("label", ""),
                        "section_hint": ref.get("section_hint", ""),
                        "first_reference_hint": ref.get("first_reference_hint", ""),
                        "source_tex": ref.get("source_tex", ""),
                        "conversion": mode,
                        "warnings": warnings,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            extraction_warnings.append(f"arXiv source extraction failed: {exc}")

    fallback_used = False
    if not figures:
        fallback_used = True
        figures, fallback_warnings = extract_pdf_fallback(raw_dir / "paper.pdf", images_dir)
        extraction_warnings.extend(fallback_warnings)

    write_json(
        cache_dir / "images_manifest.json",
        {
            "schema_version": "2.0",
            "policy": "author_source_then_pdf_embedded_then_pdf_page; never webpage_screenshot",
            "fallback_used": fallback_used,
            "figures": figures,
            "warnings": extraction_warnings,
        },
    )
    print("Validated figures extracted:", len(figures))
    return 0 if figures else 1


if __name__ == "__main__":
    raise SystemExit(main())
