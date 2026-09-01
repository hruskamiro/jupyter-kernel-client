#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${JK_PYTHON:-python3}"
INSTALLER="${JK_INSTALLER:-pipx}"
CHECK_ONLY=0
UNINSTALL=0

usage() {
  cat <<USAGE
Usage: ./install.sh [options]

Options:
  --check, check, doctor    Check dependencies and installation status only.
  uninstall, --uninstall    Uninstall the package.
  -h, --help                Show this help.

Environment:
  JK_INSTALLER              pipx or pip. Defaults to pipx.
  JK_PYTHON                 Python executable used when JK_INSTALLER=pip.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check|check|doctor)
      CHECK_ONLY=1
      shift
      ;;
    uninstall|--uninstall)
      UNINSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

report_ok() {
  printf '  [ok]   %s\n' "$1"
}

report_warn() {
  printf '  [warn] %s\n' "$1"
}

report_fail() {
  printf '  [miss] %s\n' "$1"
}

check() {
  local missing=0

  echo "Project files"
  [[ -f "${ROOT_DIR}/pyproject.toml" ]] && report_ok "pyproject.toml exists" || { report_fail "pyproject.toml is missing"; missing=1; }
  [[ -f "${ROOT_DIR}/src/jupyter_kernel_client/cli.py" ]] && report_ok "package source exists" || { report_fail "package source is missing"; missing=1; }

  echo "Install tools"
  if command -v pipx >/dev/null 2>&1; then
    report_ok "pipx: $(command -v pipx)"
  else
    report_warn "pipx is not installed; use JK_INSTALLER=pip or install pipx"
  fi

  if command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    report_ok "Python: $(${PYTHON_BIN} --version 2>&1)"
  else
    report_warn "Python not found: ${PYTHON_BIN}"
  fi

  if command -v jk >/dev/null 2>&1; then
    report_ok "jk command: $(command -v jk)"
  else
    report_warn "jk command is not installed on PATH"
  fi

  return "${missing}"
}

if [[ "${CHECK_ONLY}" -eq 1 ]]; then
  check
  exit $?
fi

check || exit $?

if [[ "${UNINSTALL}" -eq 1 ]]; then
  if [[ "${INSTALLER}" == "pipx" ]]; then
    exec pipx uninstall jupyter-kernel-cli
  fi
  exec "${PYTHON_BIN}" -m pip uninstall -y jupyter-kernel-cli
fi

if [[ "${INSTALLER}" == "pipx" ]]; then
  exec pipx install --force "${ROOT_DIR}"
fi

if [[ "${INSTALLER}" == "pip" ]]; then
  exec "${PYTHON_BIN}" -m pip install -e "${ROOT_DIR}"
fi

echo "Unknown JK_INSTALLER: ${INSTALLER}. Use pipx or pip." >&2
exit 2
