#!/bin/sh
# After the board is on screen: wait for an exit tap, then restore the UI.
#
# The home framework is frozen so it cannot paint over the image, but pillow
# and powerd stay free: idle timeout and the power button still start the
# stock screensaver. A tap while awake returns to Home. A tap that only
# wakes the device is ignored so the board comes back.
#
# Other exits:
#   - KUAL Salir or PC rescue (cache/STOP)
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

# A refresh kills the old waiter on purpose while the board stays on screen,
# so only release the framework when nothing is meant to be displayed.
_on_signal() {
	if [ ! -f "${CACHE}/showing.pid" ]; then
		log "wait-exit: signal with nothing showing, unlocking"
		unlock_ui
	else
		log "wait-exit: signal while showing, leaving UI locked"
	fi
	exit 0
}
trap _on_signal HUP INT TERM

_pids=""

_track() {
	_pids="${_pids} $1"
}

# Touch / page-turn closes the view. Power is left to powerd (screensaver).
# Keep reading in a loop: the tap that launched us from KUAL can still be
# queued, and the grace period below discards those without disabling the watcher.
for _dev in /dev/input/event*; do
	[ -r "${_dev}" ] || continue
	(
		while :; do
			if dd if="${_dev}" bs=16 count=1 >/dev/null 2>&1; then
				echo "input" > "${CACHE}/exit.reason"
			else
				exit 0
			fi
			sleep 1
		done
	) &
	_track $!
	log "wait-exit: watching ${_dev}"
done

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
_ss=0
_wake_until=0

while true; do
	if stay_awake_mode; then
		hold_awake_tick
	fi
	if in_screensaver; then
		if stay_awake_mode; then
			# Should not happen in Auto; shove powerd again and redraw.
			log "wait-exit: screensaver during stay-awake, forcing awake"
			hold_awake_tick
			redraw_showing
			_ss=0
			rm -f "${CACHE}/exit.reason" 2>/dev/null
		elif [ "${_ss}" != "1" ]; then
			log "wait-exit: screensaver"
			_ss=1
			rm -f "${CACHE}/exit.reason" 2>/dev/null
		else
			rm -f "${CACHE}/exit.reason" 2>/dev/null
		fi
	elif [ "${_ss}" = "1" ]; then
		_ss=0
		_t=$(_now)
		if [ -n "${_t}" ]; then
			_wake_until=$((_t + 4))
		fi
		log "wait-exit: woke, redraw"
		redraw_showing
		rm -f "${CACHE}/exit.reason" 2>/dev/null
	fi

	_t=$(_now)
	if [ -n "${_t}" ] && [ "${_wake_until}" -gt 0 ] && [ "${_t}" -lt "${_wake_until}" ]; then
		rm -f "${CACHE}/exit.reason" 2>/dev/null
	fi

	if [ -f "${CACHE}/STOP" ]; then
		_kill_watchers
		_exit_now stopfile
	fi
	if [ -f "${CACHE}/exit.reason" ]; then
		_r=$(cat "${CACHE}/exit.reason" 2>/dev/null)
		rm -f "${CACHE}/exit.reason"
		# Power button is also an input event. If it started the screensaver,
		# do not treat that as Salir.
		if [ "${_r}" = "input" ]; then
			sleep 1
			if in_screensaver; then
				log "wait-exit: input was power/sleep, ignoring"
				continue
			fi
		fi
		_kill_watchers
		_exit_now "${_r:-event}"
	fi
	if [ ! -f "${CACHE}/showing.pid" ]; then
		_kill_watchers
		# stop.sh normally clears this after unlocking, but if the file went
		# missing another way the framework would stay frozen for good.
		log "wait-exit: showing.pid gone, unlocking"
		unlock_ui
		rm -f "${CACHE}/waiter.pid" 2>/dev/null
		exit 0
	fi
	if [ "${_elapsed}" -ge "${_limit}" ]; then
		_kill_watchers
		_exit_now timeout
	fi
	sleep 2
	_elapsed=$((_elapsed + 2))
done
