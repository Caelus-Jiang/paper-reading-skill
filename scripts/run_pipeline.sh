#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: bash scripts/run_pipeline.sh '<arxiv url or id>' [--resume <dir>] [--force] [--force-stage <name>] [--overwrite-report] [--output-dir <dir>]"
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INPUT="$1"
shift
OUTPUT_DIR="${PWD}/output"
RESUME=""
FORCE_ALL=0
OVERWRITE_REPORT=0
FORCE_STAGES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resume|--reuse)
      [[ $# -ge 2 ]] || { usage; exit 1; }
      RESUME="$2"
      shift 2
      ;;
    --force)
      FORCE_ALL=1
      shift
      ;;
    --force-stage)
      [[ $# -ge 2 ]] || { usage; exit 1; }
      FORCE_STAGES+=("$2")
      shift 2
      ;;
    --overwrite-report)
      OVERWRITE_REPORT=1
      shift
      ;;
    --output-dir)
      [[ $# -ge 2 ]] || { usage; exit 1; }
      OUTPUT_DIR="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -d "${ROOT_DIR}/.venv-paper-reading" ]]; then
  source "${ROOT_DIR}/.venv-paper-reading/bin/activate"
fi

mkdir -p "${OUTPUT_DIR}"
DUPLICATE_ARGS=(--input "${INPUT}" --root "${OUTPUT_DIR}")
if [[ -n "${RESUME}" ]]; then
  DUPLICATE_ARGS+=(--reuse "${RESUME}")
else
  DUPLICATE_ARGS+=(--on-duplicate abort)
fi

DUP_EXIT=0
python "${ROOT_DIR}/scripts/check_duplicate.py" "${DUPLICATE_ARGS[@]}" || DUP_EXIT=$?
if [[ ${DUP_EXIT} -eq 1 ]]; then
  echo "Aborted safely: an existing workspace was found. Use --resume <dir> to continue it." >&2
  exit 1
elif [[ ${DUP_EXIT} -ne 0 && ${DUP_EXIT} -ne 2 ]]; then
  echo "Duplicate check failed with exit code ${DUP_EXIT}." >&2
  exit "${DUP_EXIT}"
fi

PREPARE_ARGS=(python "${ROOT_DIR}/scripts/prepare_workspace.py" --input "${INPUT}" --root "${OUTPUT_DIR}")
if [[ -n "${RESUME}" ]]; then
  PREPARE_ARGS+=(--workspace-name "${RESUME}")
fi
WORKSPACE_OUTPUT=$("${PREPARE_ARGS[@]}")
echo "${WORKSPACE_OUTPUT}"
WORKSPACE_DIR=$(echo "${WORKSPACE_OUTPUT}" | sed -n '1p')
WORKSPACE_DIR_NAME=$(basename "${WORKSPACE_DIR}")
PIPELINE_STATE_DIR="${WORKSPACE_DIR}/cache/pipeline_state"
PIPELINE_LOG_DIR="${WORKSPACE_DIR}/logs/pipeline"
PIPELINE_LOCK_DIR="${WORKSPACE_DIR}/cache/pipeline.lock"
PIPELINE_PID_FILE="${PIPELINE_LOCK_DIR}/pid"
mkdir -p "${PIPELINE_STATE_DIR}" "${PIPELINE_LOG_DIR}"

if ! mkdir "${PIPELINE_LOCK_DIR}" 2>/dev/null; then
  OLD_PID=$(cat "${PIPELINE_PID_FILE}" 2>/dev/null || true)
  if [[ -n "${OLD_PID}" ]] && ! kill -0 "${OLD_PID}" 2>/dev/null; then
    rm -rf "${PIPELINE_LOCK_DIR}"
    mkdir "${PIPELINE_LOCK_DIR}"
  else
    echo "Another pipeline process is using this workspace (PID: ${OLD_PID:-unknown}): ${WORKSPACE_DIR}" >&2
    exit 1
  fi
fi
printf '%s\n' "$$" > "${PIPELINE_PID_FILE}"
printf '%s\n' "$(hostname)" > "${PIPELINE_LOCK_DIR}/host"
printf '%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "${PIPELINE_LOCK_DIR}/started_at"
trap 'rm -rf "${PIPELINE_LOCK_DIR}"' EXIT INT TERM

should_force_stage() {
  local requested="$1"
  [[ ${FORCE_ALL} -eq 1 ]] && return 0
  [[ ${OVERWRITE_REPORT} -eq 1 && "${requested}" == "build_report_skeleton" ]] && return 0
  local value
  [[ ${#FORCE_STAGES[@]} -eq 0 ]] && return 1
  for value in "${FORCE_STAGES[@]}"; do
    [[ "${value}" == "${requested}" ]] && return 0
  done
  return 1
}

run_stage() {
  local stage_name="$1"
  local script_path="$2"
  shift 2
  local log_file="${PIPELINE_LOG_DIR}/${stage_name}.log"
  local state_command=(python "${ROOT_DIR}/scripts/pipeline_state.py" --workspace "${WORKSPACE_DIR}" --stage "${stage_name}" --script "${script_path}" --project-root "${ROOT_DIR}")

  if ! should_force_stage "${stage_name}" && "${state_command[@]}" is-current; then
    echo "[skip] ${stage_name} inputs and script are unchanged."
    return 0
  fi

  echo "[run] ${stage_name}"
  printf '# %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${stage_name}" > "${log_file}"
  if "$@" >> "${log_file}" 2>&1; then
    "${state_command[@]}" mark --command "$*"
    echo "[done] ${stage_name}"
    return 0
  fi
  echo "[fail] ${stage_name}. See log: ${log_file}" >&2
  return 1
}

STAGE_INPUT="${WORKSPACE_DIR_NAME}"
SKELETON_ARGS=(python "${ROOT_DIR}/scripts/build_report_skeleton.py" --input "${STAGE_INPUT}" --root "${OUTPUT_DIR}")
if [[ ${OVERWRITE_REPORT} -eq 1 ]]; then
  SKELETON_ARGS+=(--overwrite-report)
fi

run_stage fetch_sources "${ROOT_DIR}/scripts/fetch_sources.py" python "${ROOT_DIR}/scripts/fetch_sources.py" --input "${STAGE_INPUT}" --root "${OUTPUT_DIR}"
run_stage extract_references "${ROOT_DIR}/scripts/extract_references.py" python "${ROOT_DIR}/scripts/extract_references.py" --input "${STAGE_INPUT}" --root "${OUTPUT_DIR}"
run_stage extract_images "${ROOT_DIR}/scripts/extract_images.py" python "${ROOT_DIR}/scripts/extract_images.py" --input "${STAGE_INPUT}" --root "${OUTPUT_DIR}"
run_stage extract_paper_text "${ROOT_DIR}/scripts/extract_paper_text.py" python "${ROOT_DIR}/scripts/extract_paper_text.py" --input "${STAGE_INPUT}" --root "${OUTPUT_DIR}"
run_stage build_report_skeleton "${ROOT_DIR}/scripts/build_report_skeleton.py" "${SKELETON_ARGS[@]}"
run_stage validate_report_text "${ROOT_DIR}/scripts/validate_report_text.py" python "${ROOT_DIR}/scripts/validate_report_text.py" --paper-input "${STAGE_INPUT}" --root "${OUTPUT_DIR}"
run_stage paper_index "${ROOT_DIR}/scripts/paper_index.py" python "${ROOT_DIR}/scripts/paper_index.py" --root "${OUTPUT_DIR}" --add "${WORKSPACE_DIR_NAME}"

echo "Pipeline complete: ${WORKSPACE_DIR}"
echo "Stage state: ${PIPELINE_STATE_DIR}"
