#!/bin/sh
# Shared helpers for Calendario KUAL extension.

EXT="/mnt/us/extensions/calendar"
BIN="${EXT}/bin"
CACHE="${EXT}/cache"
CONFIG="${BIN}/config"
IMG="${EXT}/calendar.png"
LOG="${CACHE}/calendar.log"

mkdir -p "${CACHE}" 2>/dev/null

log() {
	echo "$(date 2>/dev/null) $*" >> "${LOG}" 2>/dev/null
}

load_config() {
	if [ -f "${CONFIG}" ]; then
		_tmp="${CACHE}/config.cleaned"
		tr -d '\r' < "${CONFIG}" > "${_tmp}" 2>/dev/null || cp "${CONFIG}" "${_tmp}"
		# shellcheck disable=SC1090
		. "${_tmp}"
	fi
	: "${CALENDAR_URL:=}"
	: "${WGET_INSECURE:=1}"
	: "${FBINK:=/mnt/us/libkh/bin/fbink}"
	FBINK=$(echo "${FBINK}" | tr -d '\r')
	CALENDAR_URL=$(echo "${CALENDAR_URL}" | tr -d '\r')

	if [ ! -f "${FBINK}" ]; then
		for c in /mnt/us/libkh/bin/fbink /mnt/us/extensions/MRInstaller/bin/K5/fbink; do
			[ -f "$c" ] && FBINK="$c" && break
		done
	fi
}

find_image() {
	for c in "${IMG}" "/mnt/us/documents/calendar.png" "/mnt/us/calendar.png"; do
		if [ -f "$c" ] && is_png "$c"; then
			echo "$c"
			return 0
		fi
	done
	return 1
}

# PNG magic: 89 50 4E 47
is_png() {
	[ -f "$1" ] || return 1
	_od=$(od -An -tx1 -N4 "$1" 2>/dev/null | tr -d ' \n')
	[ "${_od}" = "89504e47" ]
}

wifi_on() {
	lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
	_n=0
	while [ "${_n}" -lt 25 ]; do
		_st=$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null || echo "")
		case "${_st}" in
			CONNECTED|CONNECTED_PENDING) return 0 ;;
		esac
		sleep 1
		_n=$((_n + 1))
	done
	return 1
}

wifi_off() {
	lipc-set-prop com.lab126.cmd wirelessEnable 0 2>/dev/null
}

lock_ui() {
	# Do not set preventScreenSaver: power button can still fire events so wait-exit can Salir.
	killall -STOP mesquite 2>/dev/null
	lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
}

unlock_ui() {
	killall -CONT mesquite 2>/dev/null
	lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
	lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
	lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
}

kill_waiter() {
	if [ -f "${CACHE}/waiter.pid" ]; then
		_w=$(cat "${CACHE}/waiter.pid" 2>/dev/null)
		[ -n "${_w}" ] && kill "${_w}" 2>/dev/null
		rm -f "${CACHE}/waiter.pid"
	fi
	pkill -f "extensions/calendar/bin/wait-exit" 2>/dev/null
}

start_waiter() {
	kill_waiter
	rm -f "${CACHE}/exit.reason" "${CACHE}/STOP" 2>/dev/null
	/bin/sh "${BIN}/wait-exit.sh" >> "${LOG}" 2>&1 &
	echo $! > "${CACHE}/waiter.pid"
}

# Try FBInk image flags used across builds; fall back to eips -g.
draw_png() {
	_img="$1"
	if [ -n "${FBINK}" ] && [ -f "${FBINK}" ]; then
		# Prefer a single flashing paint (clear + image).
		if "${FBINK}" -g "file=${_img}" -f >> "${LOG}" 2>&1; then
			return 0
		fi
		if "${FBINK}" -c -g "file=${_img}" -f >> "${LOG}" 2>&1; then
			return 0
		fi
		# Older / alternate CLI
		if "${FBINK}" -i "${_img}" -f >> "${LOG}" 2>&1; then
			return 0
		fi
		log "fbink image flags failed; fbink -h follows"
		"${FBINK}" -h >> "${LOG}" 2>&1
	else
		log "draw_png: no fbink at '${FBINK}'"
	fi
	# Last resort on some firmwares
	if /usr/sbin/eips -g "${_img}" >> "${LOG}" 2>&1; then
		return 0
	fi
	return 1
}

display_image() {
	_path="$1"
	if [ -z "${_path}" ] || [ ! -f "${_path}" ]; then
		/usr/sbin/eips 2 3 "Falta calendar.png" 2>/dev/null
		log "display: missing path"
		return 1
	fi
	if ! is_png "${_path}"; then
		/usr/sbin/eips 2 3 "PNG invalido" 2>/dev/null
		log "display: not a png: ${_path}"
		return 1
	fi
	if [ -z "${FBINK}" ] || [ ! -f "${FBINK}" ]; then
		/usr/sbin/eips 2 3 "Falta fbink" 2>/dev/null
		log "display: missing fbink"
		return 1
	fi

	# Detach: paint AFTER leaving KUAL, and redraw after freezing mesquite.
	# If we STOP mesquite then fail to paint, the chrome is gone and the screen stays blank.
	(
		sleep 1
		log "display: start ${_path}"
		# First paint while UI still alive (proves image works).
		if ! draw_png "${_path}"; then
			/usr/sbin/eips -c 2>/dev/null
			/usr/sbin/eips 2 3 "No se pudo dibujar" 2>/dev/null
			/usr/sbin/eips 2 5 "Ver cache/calendar.log" 2>/dev/null
			log "display: draw failed before lock"
			exit 1
		fi
		lock_ui
		# Mesquite may have painted over us when freezing — paint again.
		if ! draw_png "${_path}"; then
			unlock_ui
			/usr/sbin/eips 2 3 "No se pudo dibujar" 2>/dev/null
			log "display: draw failed after lock"
			exit 1
		fi
		echo "1" > "${CACHE}/showing.pid"
		start_waiter
		log "display: ok ${_path}"
	) >/dev/null 2>&1 &
	return 0
}
