#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/run_pipeline.sh '<arxiv url or id>' [--reuse <dir>] [--force]"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="$1"
## Shift the first argument out
shift
OUTPUT_DIR="${PWD}/output"

# Parse optional flags
REUSE=""
FORCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reuse)
      REUSE="$2"
      shift 2
      ;;
    --force)
      FORCE="--force"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -d "${ROOT_DIR}/.venv-paper-reading" ]]; then
  source "${ROOT_DIR}/.venv-paper-reading/bin/activate"
fi

mkdir -p "${OUTPUT_DIR}"

# Check for duplicate papers before proceeding
REUSE_FLAG=""
if [[ -n "${REUSE}" ]]; then
  REUSE_FLAG="--reuse ${REUSE}"
fi
DUP_EXIT=0
python "${ROOT_DIR}/scripts/check_duplicate.py" --input "${INPUT}" --root "${OUTPUT_DIR}" ${REUSE_FLAG} ${FORCE} || DUP_EXIT=$?
if [[ ${DUP_EXIT} -eq 1 ]]; then
  echo "Aborted: duplicate paper exists and user chose not to overwrite."
  exit 1
elif [[ ${DUP_EXIT} -eq 2 ]]; then
  echo "Reusing existing workspace. Skipping pipeline."
  exit 0
fi

WORKSPACE_OUTPUT=$(python "${ROOT_DIR}/scripts/prepare_workspace.py" --input "${INPUT}" --root "${OUTPUT_DIR}")
echo "${WORKSPACE_OUTPUT}"
WORKSPACE_DIR=$(echo "${WORKSPACE_OUTPUT}" | head -1)
WORKSPACE_DIR_NAME=$(basename "${WORKSPACE_DIR}")

python "${ROOT_DIR}/scripts/fetch_sources.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/extract_references.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/extract_images.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/build_report_skeleton.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
python "${ROOT_DIR}/scripts/validate_report_text.py" --input "${INPUT}" --root "${OUTPUT_DIR}"

# Update paper index after successful pipeline
python "${ROOT_DIR}/scripts/paper_index.py" --root "${OUTPUT_DIR}" --add "${WORKSPACE_DIR_NAME}"

echo "Pipeline complete."

# tips for windows users
# echo "Tip: before reading/editing Chinese reports in Windows PowerShell, run:"
# echo "  \$utf8=[System.Text.UTF8Encoding]::new(\$false); chcp 65001 > \$null; [Console]::InputEncoding=\$utf8; [Console]::OutputEncoding=\$utf8; \$OutputEncoding=\$utf8"
# echo "Re-run the text validator before delivery if the report was edited manually."
