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
		if [ -f "$c" ]; then
			echo "$c"
			return 0
		fi
	done
	return 1
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
	kill_waite
	rm -f "${CACHE}/exit.reason" "${CACHE}/STOP" 2>/dev/null
	/bin/sh "${BIN}/wait-exit.sh" >> "${LOG}" 2>&1 &
}

display_image() {
	_path="$1"
	if [ -z "${FBINK}" ] || [ ! -f "${FBINK}" ]; then
		/usr/sbin/eips 2 3 "Falta fbink" 2>/dev/null
		return 1
	fi
	if [ -z "${_path}" ] || [ ! -f "${_path}" ]; then
		/usr/sbin/eips 2 3 "Falta calendar.png" 2>/dev/null
		return 1
	fi
	lock_ui
	"${FBINK}" -q -c -f 2>/dev/null
	"${FBINK}" -q -g "file=${_path}" -f 2>/dev/null
	echo "1" > "${CACHE}/showing.pid"
	log "display ${_path}"
	start_waite
	return 0
}
