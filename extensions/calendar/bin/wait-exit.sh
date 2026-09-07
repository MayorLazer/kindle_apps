#!/bin/sh
# After calendar is on screen: wait for exit signal, then restore UI.
# Triggers: power button, USB plug, or cache/STOP file.

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

echo $$ > "${CACHE}/waiter.pid"
log "wait-exit: started pid=$$"

_exit_now() {
	log "wait-exit: trigger=$1"
	rm -f "${CACHE}/waiter.pid" "${CACHE}/showing.pid" "${CACHE}/STOP" 2>/dev/null
	/bin/sh "${BIN}/stop.sh"
	exit 0
}

# Prefer event wait; fall back to polling.
if command -v lipc-wait-event >/dev/null 2>&1; then
	(
		lipc-wait-event com.lab126.powerd powerButtonPressed >/dev/null 2>&1
		echo power > "${CACHE}/exit.reason"
	) &
	_p1=$!
	(
		lipc-wait-event com.lab126.hal usbPlugIn >/dev/null 2>&1
		echo usb > "${CACHE}/exit.reason"
	) &
	_p2=$!
	(
		lipc-wait-event com.lab126.powerd goingToScreenSaver >/dev/null 2>&1
		echo screensaver > "${CACHE}/exit.reason"
	) &
	_p3=$!

	while true; do
		if [ -f "${CACHE}/STOP" ]; then
			kill "${_p1}" "${_p2}" "${_p3}" 2>/dev/null
			_exit_now stopfile
		fi
		if [ -f "${CACHE}/exit.reason" ]; then
			_r=$(cat "${CACHE}/exit.reason" 2>/dev/null)
			rm -f "${CACHE}/exit.reason"
			kill "${_p1}" "${_p2}" "${_p3}" 2>/dev/null
			_exit_now "${_r:-event}"
		fi
		# If UI lock was cleared externally, exit waite
		_ps=$(lipc-get-prop com.lab126.powerd preventScreenSaver 2>/dev/null || echo "")
		if [ "${_ps}" = "0" ] && [ ! -f "${CACHE}/showing.pid" ]; then
			kill "${_p1}" "${_p2}" "${_p3}" 2>/dev/null
			exit 0
		fi
		sleep 1
	done
fi

# Fallback poll loop
while true; do
	[ -f "${CACHE}/STOP" ] && _exit_now stopfile
	sleep 2
done
