#!/bin/sh
set -eu
umask 077

log() {
    printf '%s\n' "[openhop-repeater-ha] $*"
}

fatal() {
    printf '%s\n' "[openhop-repeater-ha] ERROR: $*" >&2
    exit 1
}

CONFIG_DIR="${OPENHOP_ADDON_CONFIG_DIR:-/config}"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
DATA_DIR="${OPENHOP_ADDON_DATA_DIR:-/var/lib/openhop_repeater}"
RUNTIME_CONFIG_DIR="${OPENHOP_ADDON_RUNTIME_CONFIG_DIR:-/etc/openhop_repeater}"
TEMPLATE_CONFIG_FILE="${OPENHOP_ADDON_TEMPLATE_CONFIG:-/usr/share/openhop-repeater/config.yaml.example}"
CONFIG_HELPER="${OPENHOP_ADDON_CONFIG_HELPER:-/usr/local/lib/openhop-addon/config_bootstrap.py}"
PYTHON="${OPENHOP_ADDON_PYTHON:-$(command -v python3)}"
STABLE_SECONDS="${OPENHOP_ADDON_STABLE_SECONDS:-30}"
MAX_RAPID_RESTARTS="${OPENHOP_ADDON_MAX_RAPID_RESTARTS:-3}"
RESTART_DELAY="${OPENHOP_ADDON_RESTART_DELAY:-1}"
STOP_TIMEOUT="${OPENHOP_ADDON_STOP_TIMEOUT:-8}"

for integer_value in "${STABLE_SECONDS}" "${MAX_RAPID_RESTARTS}" "${STOP_TIMEOUT}"; do
    case "${integer_value}" in
        ''|*[!0-9]*) fatal "lifecycle limits must be non-negative integers" ;;
    esac
done

if [ -z "${PYTHON}" ] || [ ! -x "${PYTHON}" ]; then
    fatal "python3 is unavailable"
fi
[ -r "${TEMPLATE_CONFIG_FILE}" ] || fatal "packaged configuration template is missing"
[ -r "${CONFIG_HELPER}" ] || fatal "configuration bootstrap helper is missing"

# Some upstream images install Python packages into a non-root user's local
# site-packages directory. Make those dependencies visible before invoking the
# bootstrap helper as well as the repeater runtime.
for site_dir in /home/*/.local/lib/python*/site-packages; do
    if [ -d "${site_dir}" ]; then
        PYTHONPATH="${site_dir}${PYTHONPATH:+:${PYTHONPATH}}"
    fi
done
export PYTHONPATH

mkdir -p "${CONFIG_DIR}" "${DATA_DIR}"
"${PYTHON}" "${CONFIG_HELPER}" bootstrap "${TEMPLATE_CONFIG_FILE}" "${CONFIG_FILE}"

if [ "$(readlink "${RUNTIME_CONFIG_DIR}" 2>/dev/null || true)" != "${CONFIG_DIR}" ]; then
    rm -rf "${RUNTIME_CONFIG_DIR}"
    mkdir -p "$(dirname "${RUNTIME_CONFIG_DIR}")"
    ln -s "${CONFIG_DIR}" "${RUNTIME_CONFIG_DIR}"
fi

# Older channel images predate the plugin manager. Only fall back when its
# supervisor module is absent, never when an installed supervisor fails to run.
RUNTIME_MODULE="$("${PYTHON}" -c '
import importlib.util

module = "repeater.plugins.container_supervisor"
try:
    spec = importlib.util.find_spec(module)
except ModuleNotFoundError as exc:
    if exc.name not in {"repeater.plugins", module}:
        raise
    spec = None
print(module if spec is not None else "repeater.main")
')"
log "using runtime ${RUNTIME_MODULE}"

CHILD_PID=""
STOP_REQUESTED=false

forward_stop() {
    STOP_REQUESTED=true
    if [ -n "${CHILD_PID}" ]; then
        kill -TERM "${CHILD_PID}" 2>/dev/null || true
    fi
}
trap forward_stop TERM INT

stop_child_and_wait() {
    child_pid="$1"
    kill -TERM "${child_pid}" 2>/dev/null || true
    "${PYTHON}" -c '
import os
import signal
import sys
import time

time.sleep(int(sys.argv[2]))
try:
    os.kill(int(sys.argv[1]), signal.SIGKILL)
except ProcessLookupError:
    pass
' "${child_pid}" "${STOP_TIMEOUT}" &
    watchdog_pid=$!
    wait "${child_pid}" 2>/dev/null || true
    kill "${watchdog_pid}" 2>/dev/null || true
    wait "${watchdog_pid}" 2>/dev/null || true
}

rapid_restarts=0
while :; do
    if [ "${STOP_REQUESTED}" = "true" ]; then
        exit 0
    fi
    started_at="$(date +%s)"
    "${PYTHON}" -m "${RUNTIME_MODULE}" --config "${RUNTIME_CONFIG_DIR}/config.yaml" &
    CHILD_PID=$!
    if [ "${STOP_REQUESTED}" = "true" ]; then
        kill -TERM "${CHILD_PID}" 2>/dev/null || true
    fi
    log "repeater process started"

    exit_code=0
    wait "${CHILD_PID}" || exit_code=$?

    if [ "${STOP_REQUESTED}" = "true" ]; then
        stop_child_and_wait "${CHILD_PID}"
        CHILD_PID=""
        exit 0
    fi
    CHILD_PID=""

    if [ "${exit_code}" -ne 0 ]; then
        fatal "repeater exited unexpectedly with status ${exit_code}"
    fi

    stopped_at="$(date +%s)"
    runtime_seconds=$((stopped_at - started_at))
    if [ "${runtime_seconds}" -ge "${STABLE_SECONDS}" ]; then
        rapid_restarts=0
    fi
    rapid_restarts=$((rapid_restarts + 1))
    if [ "${rapid_restarts}" -gt "${MAX_RAPID_RESTARTS}" ]; then
        fatal "rapid restart limit exceeded after ${rapid_restarts} clean exits"
    fi

    log "repeater requested a restart; starting the packaged runtime again"
    sleep "${RESTART_DELAY}" || true
done
