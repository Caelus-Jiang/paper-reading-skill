#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: bash scripts/run_pipeline.sh '<arxiv url or id>' [--reuse <dir>] [--force]"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="$1"
shift
OUTPUT_DIR="${PWD}/output"

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
WORKSPACE_DIR=$(echo "${WORKSPACE_OUTPUT}" | sed -n '1p')
WORKSPACE_DIR_NAME=$(basename "${WORKSPACE_DIR}")
PIPELINE_STATE_DIR="${WORKSPACE_DIR}/cache/pipeline_state"
PIPELINE_LOG_DIR="${WORKSPACE_DIR}/logs/pipeline"
mkdir -p "${PIPELINE_STATE_DIR}" "${PIPELINE_LOG_DIR}"

run_stage() {
  local stage_name="$1"
  shift
  local done_marker="${PIPELINE_STATE_DIR}/${stage_name}.done"
  local log_file="${PIPELINE_LOG_DIR}/${stage_name}.log"

  if [[ -f "${done_marker}" && -z "${FORCE}" ]]; then
    echo "[skip] ${stage_name} already completed. Use --force to rerun."
    return 0
  fi

  echo "[run] ${stage_name}"
  echo "# $(date '+%Y-%m-%d %H:%M:%S') ${stage_name}" > "${log_file}"
  if "$@" >> "${log_file}" 2>&1; then
    date '+%Y-%m-%d %H:%M:%S' > "${done_marker}"
    echo "[done] ${stage_name}"
    return 0
  fi

  echo "[fail] ${stage_name}. See log: ${log_file}" >&2
  return 1
}

run_stage fetch_sources python "${ROOT_DIR}/scripts/fetch_sources.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
run_stage extract_references python "${ROOT_DIR}/scripts/extract_references.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
run_stage extract_images python "${ROOT_DIR}/scripts/extract_images.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
run_stage build_report_skeleton python "${ROOT_DIR}/scripts/build_report_skeleton.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
run_stage validate_report_text python "${ROOT_DIR}/scripts/validate_report_text.py" --input "${INPUT}" --root "${OUTPUT_DIR}"
run_stage paper_index python "${ROOT_DIR}/scripts/paper_index.py" --root "${OUTPUT_DIR}" --add "${WORKSPACE_DIR_NAME}"

echo "Pipeline complete. Stage markers: ${PIPELINE_STATE_DIR}"
