#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/run_pipeline.sh '<arxiv url or id>'"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="$1"
OUTPUT_DIR="${PWD}/output"
OBSIDIAN_PAPER_NOTES_DIR="${OBSIDIAN_PAPER_NOTES_DIR:-}"
OBSIDIAN_IMAGE_DIR="${OBSIDIAN_IMAGE_DIR:-}"

if [[ -d "${ROOT_DIR}/.venv-paper-reading" ]]; then
  source "${ROOT_DIR}/.venv-paper-reading/bin/activate"
fi

mkdir -p "${OUTPUT_DIR}"

python "${ROOT_DIR}/scripts/prepare_workspace.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/fetch_sources.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/extract_references.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/extract_images.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/build_report_skeleton.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/validate_report_text.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
 
# 同步到 Obsidian
if [[ -n "${OBSIDIAN_PAPER_NOTES_DIR}" || -n "${OBSIDIAN_IMAGE_DIR}" ]]; then
  if [[ -z "${OBSIDIAN_PAPER_NOTES_DIR}" || -z "${OBSIDIAN_IMAGE_DIR}" ]]; then
    echo "ERROR: set both OBSIDIAN_PAPER_NOTES_DIR and OBSIDIAN_IMAGE_DIR to enable Obsidian sync." >&2
    exit 1
  fi
  python "${ROOT_DIR}/scripts/sync_obsidian.py" \
    --input "${INPUT}" \
    --root "${OUTPUT_DIR}" \
    --notes-dir "${OBSIDIAN_PAPER_NOTES_DIR}" \
    --images-dir "${OBSIDIAN_IMAGE_DIR}"
fi

echo "Pipeline complete."

# tips for windows users
# echo "Tip: before reading/editing Chinese reports in Windows PowerShell, run:"
# echo "  \$utf8=[System.Text.UTF8Encoding]::new(\$false); chcp 65001 > \$null; [Console]::InputEncoding=\$utf8; [Console]::OutputEncoding=\$utf8; \$OutputEncoding=\$utf8"
# echo "Re-run the text validator before delivery if the report was edited manually."
