#!/bin/sh
# After the calendar is on screen: wait for an exit signal, then restore the UI.
#
# The framework is frozen while the calendar shows, so touch no longer reaches
# KUAL. Exit therefore has to come from raw input events:
#   - any touch / button (reads /dev/input/event*)
#   - KUAL Salir or PC rescue (cache/STOP)
#   - lipc power event, when lipc-wait-event exists
#   - safety timeout, so the device can never get stuck

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

: "${EXIT_TIMEOUT_MIN:=120}"

echo $$ > "${CACHE}/waiter.pid"
log "wait-exit: started pid=$$ timeout=${EXIT_TIMEOUT_MIN}min"

_now() {
	date +%s 2>/dev/null | tr -cd '0-9'
}

_exit_now() {
	log "wait-exit: trigger=$1"
	rm -f "${CACHE}/waiter.pid" "${CACHE}/showing.pid" "${CACHE}/STOP" 2>/dev/null
	/bin/sh "${BIN}/stop.sh"
	exit 0
}

_pids=""

_track() {
	_pids="${_pids} $1"
}

# Any input event (touch, page turn, power) closes the view. One 16-byte
# input_event record is enough; dd blocks until something happens.
for _dev in /dev/input/event*; do
	[ -r "${_dev}" ] || continue
	(
		if dd if="${_dev}" bs=16 count=1 >/dev/null 2>&1; then
			echo "input" > "${CACHE}/exit.reason"
		fi
	) &
	_track $!
	log "wait-exit: watching ${_dev}"
done

if [ -n "${LIPC_WAIT}" ]; then
	(
		_t0=$(_now)
		"${LIPC_WAIT}" com.lab126.powerd powerButtonPressed >/dev/null 2>&1
		_rc=$?
		_t1=$(_now)
		if [ "${_rc}" != "0" ]; then
			log "wait-exit: power watcher unsupported (rc=${_rc})"
			exit 0
		fi
		if [ -n "${_t0}" ] && [ -n "${_t1}" ] && [ "$((_t1 - _t0))" -lt 2 ]; then
			log "wait-exit: power watcher returned instantly, ignoring"
			exit 0
		fi
		echo "power" > "${CACHE}/exit.reason"
	) &
	_track $!
fi

_kill_watchers() {
	for _p in ${_pids}; do
		[ -n "${_p}" ] && kill "${_p}" 2>/dev/null
	done
}

# Ignore anything that fires while the image is still being painted.
_grace=4
while [ "${_grace}" -gt 0 ]; do
	rm -f "${CACHE}/exit.reason" 2>/dev/null
	[ -f "${CACHE}/STOP" ] && break
	sleep 1
	_grace=$((_grace - 1))
done

_elapsed=0
_limit=$((EXIT_TIMEOUT_MIN * 60))
while true; do
	if [ -f "${CACHE}/STOP" ]; then
		_kill_watchers
		_exit_now stopfile
	fi
	if [ -f "${CACHE}/exit.reason" ]; then
		_r=$(cat "${CACHE}/exit.reason" 2>/dev/null)
		rm -f "${CACHE}/exit.reason"
		_kill_watchers
		_exit_now "${_r:-event}"
	fi
	if [ ! -f "${CACHE}/showing.pid" ]; then
		_kill_watchers
		log "wait-exit: showing.pid gone, exiting"
		exit 0
	fi
	if [ "${_elapsed}" -ge "${_limit}" ]; then
		_kill_watchers
		_exit_now timeout
	fi
	sleep 2
	_elapsed=$((_elapsed + 2))
done
