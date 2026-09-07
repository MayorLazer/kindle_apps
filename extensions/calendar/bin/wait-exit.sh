#!/bin/sh
# After calendar is on screen: wait for an exit signal, then restore UI.
# Triggers: power button, USB plug, KUAL Salir (cache/STOP).
#
# Watchers must only report when lipc-wait-event actually waited. An unsupported
# event name returns immediately, which used to close the calendar right away.

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

echo $$ > "${CACHE}/waiter.pid"
log "wait-exit: started pid=$$"

_now() {
	date +%s 2>/dev/null | tr -cd '0-9'
}

_exit_now() {
	log "wait-exit: trigger=$1"
	rm -f "${CACHE}/waiter.pid" "${CACHE}/showing.pid" "${CACHE}/STOP" 2>/dev/null
	/bin/sh "${BIN}/stop.sh"
	exit 0
}

# watch <name> <lipc source> <event>
watch() {
	_name="$1"
	_src="$2"
	_ev="$3"
	(
		_t0=$(_now)
		"${LIPC_WAIT}" "${_src}" "${_ev}" >/dev/null 2>&1
		_rc=$?
		_t1=$(_now)
		if [ "${_rc}" != "0" ]; then
			log "wait-exit: ${_name} unsupported (rc=${_rc})"
			exit 0
		fi
		# A "successful" instant return means the event source is not usable here.
		if [ -n "${_t0}" ] && [ -n "${_t1}" ] && [ "$((_t1 - _t0))" -lt 2 ]; then
			log "wait-exit: ${_name} returned instantly, ignoring"
			exit 0
		fi
		echo "${_name}" > "${CACHE}/exit.reason"
	) &
	echo $!
}

_pids=""
if [ -n "${LIPC_WAIT}" ]; then
	_pids="$(watch power com.lab126.powerd powerButtonPressed)"
	_pids="${_pids} $(watch usb com.lab126.hal usbPlugIn)"
else
	log "wait-exit: no lipc-wait-event; polling screensaver + STOP file"
fi

# Without events, detect sleep/screensaver by polling powerd.
_screensaver_active() {
	[ -n "${LIPC_WAIT}" ] && return 1
	_st=$(lipc-get-prop com.lab126.powerd status 2>/dev/null)
	case "${_st}" in
		*creenSaver*|*creen\ Saver*|*creensaver*) return 0 ;;
	esac
	return 1
}

_kill_watchers() {
	for _p in ${_pids}; do
		[ -n "${_p}" ] && kill "${_p}" 2>/dev/null
	done
}

# Grace period: drop any reason written while the image was still being drawn.
_grace=4
while [ "${_grace}" -gt 0 ]; do
	rm -f "${CACHE}/exit.reason" 2>/dev/null
	[ -f "${CACHE}/STOP" ] && break
	sleep 1
	_grace=$((_grace - 1))
done

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
	if _screensaver_active; then
		_kill_watchers
		_exit_now screensaver
	fi
	# Salir (or anything else) cleared our marker: stop watching, leave UI alone.
	if [ ! -f "${CACHE}/showing.pid" ]; then
		_kill_watchers
		log "wait-exit: showing.pid gone, exiting"
		exit 0
	fi
	sleep 2
done
