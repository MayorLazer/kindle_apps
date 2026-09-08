#!/bin/sh
# Shared helpers for the Tablero KUAL extension (Hoy / Calendario / Clima / Mes).

EXT="/mnt/us/extensions/calendar"
BIN="${EXT}/bin"
CACHE="${EXT}/cache"
CONFIG="${BIN}/config"
VIEW="calendar"
IMG="${EXT}/calendar.png"
LOG="${CACHE}/calendar.log"

mkdir -p "${CACHE}" 2>/dev/null

# Keep the log from filling the device: curl output and fbink dumps add up.
LOG_MAX=262144

rotate_log() {
	[ -f "${LOG}" ] || return 0
	_lsz=$(wc -c < "${LOG}" 2>/dev/null | tr -cd '0-9')
	[ -n "${_lsz}" ] || return 0
	if [ "${_lsz}" -gt "${LOG_MAX}" ]; then
		mv -f "${LOG}" "${LOG}.1" 2>/dev/null
	fi
}

log() {
	echo "$(date 2>/dev/null) $*" >> "${LOG}" 2>/dev/null
}

load_config() {
	rotate_log
	if [ -f "${CONFIG}" ]; then
		_tmp="${CACHE}/config.cleaned"
		tr -d '\r' < "${CONFIG}" > "${_tmp}" 2>/dev/null || cp "${CONFIG}" "${_tmp}"
		# shellcheck disable=SC1090
		. "${_tmp}"
	fi
	: "${CALENDAR_URL:=}"
	: "${WGET_INSECURE:=1}"
	: "${FBINK:=/mnt/us/libkh/bin/fbink}"
	: "${CURL:=}"
	: "${CALENDAR_TOKEN:=}"
	: "${VIEW:=calendar}"
	# Safety net: restore the UI even if no exit event ever arrives.
	: "${EXIT_TIMEOUT_MIN:=120}"
	# Auto refresh interval while the calendar stays on screen.
	: "${AUTO_REFRESH_MIN:=240}"
	FBINK=$(echo "${FBINK}" | tr -d '\r')
	CALENDAR_URL=$(echo "${CALENDAR_URL}" | tr -d '\r')
	CURL=$(echo "${CURL}" | tr -d '\r')
	CALENDAR_TOKEN=$(echo "${CALENDAR_TOKEN}" | tr -d '\r')

	if [ ! -f "${FBINK}" ]; then
		for c in /mnt/us/libkh/bin/fbink /mnt/us/extensions/MRInstaller/bin/K5/fbink; do
			[ -f "$c" ] && FBINK="$c" && break
		done
	fi

	# KUAL's PATH can be minimal; resolve lipc-wait-event explicitly.
	LIPC_WAIT=""
	for c in lipc-wait-event /usr/bin/lipc-wait-event /usr/local/bin/lipc-wait-event; do
		if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then
			LIPC_WAIT="$c"
			break
		fi
	done

	set_view "${VIEW}"

	if [ -z "${CURL}" ] || [ ! -f "${CURL}" ]; then
		CURL=""
		for c in \
			"${BIN}/curl" \
			/mnt/us/usbnet/bin/curl \
			/mnt/us/libkh/bin/curl \
			/mnt/us/extensions/MRInstaller/bin/K5/curl \
			/usr/bin/curl; do
			# vfat often has no reliable +x bit — test -f only
			if [ -f "$c" ]; then
				CURL="$c"
				break
			fi
		done
	fi
}

# calendar | today | weather | month. IMG and the download URL follow the view.
# CALENDAR_URL is the calendar.png address; siblings replace that filename.
set_view() {
	VIEW="$1"
	case "${VIEW}" in
		calendar|today|weather|month) ;;
		*) VIEW="calendar" ;;
	esac
	IMG="${EXT}/${VIEW}.png"
}

view_label() {
	case "${VIEW}" in
		today) echo "hoy" ;;
		weather) echo "clima" ;;
		month) echo "mes" ;;
		*) echo "calendario" ;;
	esac
}

url_for_view() {
	_url="${CALENDAR_URL}"
	case "${_url}" in
		*.png*)
			# BusyBox sed: swap the PNG filename, keep ?query if any.
			echo "${_url}" | sed "s#[^/?]*\\.png#${VIEW}.png#"
			;;
		*)
			echo "${_url%/}/${VIEW}.png"
			;;
	esac
}

# PW4 stock BusyBox 1.17 wget: only -csq -O -P -U -Y; HTTP/FTP only (no HTTPS,
# no -T, no --no-check-certificate). Prefer curl for https:// URLs.
download_url() {
	_url="$1"
	_out="$2"
	rm -f "${_out}"

	case "${_url}" in
		https://*)
			if [ -n "${CURL}" ] && [ -f "${CURL}" ]; then
				log "download: curl ${CURL} ${_url}"
				# CALENDAR_TOKEN reads a private repo over raw.githubusercontent
				# so the calendar is not published on a public URL.
				if [ -n "${CALENDAR_TOKEN}" ]; then
					"${CURL}" -k -sS -L --fail -A "KindleCalendar/1.0" \
						-H "Authorization: Bearer ${CALENDAR_TOKEN}" \
						-H "Accept: application/vnd.github.raw" \
						-o "${_out}" "${_url}" >> "${LOG}" 2>&1
				else
					"${CURL}" -k -sS -L --fail -A "KindleCalendar/1.0" \
						-o "${_out}" "${_url}" >> "${LOG}" 2>&1
				fi
				_rc=$?
				if [ "${_rc}" = "0" ] && [ -s "${_out}" ]; then
					return 0
				fi
				log "download: curl failed rc=${_rc}"
				# curl leaves a partial file behind; wget cleans up itself.
				rm -f "${_out}"
			else
				log "download: https needs curl (BusyBox wget has no SSL)"
			fi
			;;
	esac

	log "download: wget -O ${_out} ${_url}"
	# Flags must stay compatible with BusyBox 1.17.1 (Kindle PW4).
	if wget -q -U "KindleCalendar/1.0" -O "${_out}" "${_url}" >> "${LOG}" 2>&1 \
		&& [ -s "${_out}" ]; then
		return 0
	fi
	log "download: wget failed"
	rm -f "${_out}"
	return 1
}

find_image() {
	for c in "${IMG}" "/mnt/us/documents/${VIEW}.png" "/mnt/us/${VIEW}.png"; do
		if [ -f "$c" ] && is_png "$c"; then
			echo "$c"
			return 0
		fi
	done
	# Old USB drops only copied calendar.png; keep that fallback for the week view.
	if [ "${VIEW}" = "calendar" ]; then
		for c in "/mnt/us/documents/calendar.png" "/mnt/us/calendar.png"; do
			if [ -f "$c" ] && is_png "$c"; then
				echo "$c"
				return 0
			fi
		done
	fi
	return 1
}

# PNG magic: 89 'P' 'N' 'G'. BusyBox od/dd flags vary, so try a few probes and
# treat "cannot determine" as OK rather than rejecting a good download.
is_png() {
	[ -f "$1" ] || return 1

	# Bytes 2-4 are the ASCII letters PNG.
	_sig=$(dd if="$1" bs=1 skip=1 count=3 2>/dev/null)
	if [ -n "${_sig}" ]; then
		[ "${_sig}" = "PNG" ] && return 0
		log "is_png: sig='${_sig}' for $1"
		return 1
	fi

	_hex=$(od -An -tx1 -N4 "$1" 2>/dev/null | tr -d ' \t\n')
	if [ -n "${_hex}" ]; then
		case "${_hex}" in
			89504e47*) return 0 ;;
		esac
		log "is_png: hex='${_hex}' for $1"
		return 1
	fi

	log "is_png: no dd/od probe available, accepting $1"
	return 0
}

# A PNG ends with the IEND chunk. A download cut short by Wi-Fi dropping still
# has a valid header, so check the trailer before replacing a good cache.
png_complete() {
	[ -f "$1" ] || return 1
	_end=$(tail -c 8 "$1" 2>/dev/null | dd bs=1 count=4 2>/dev/null)
	if [ -z "${_end}" ]; then
		log "png_complete: no tail/dd probe, accepting $1"
		return 0
	fi
	[ "${_end}" = "IEND" ] && return 0
	log "png_complete: truncated, trailer='${_end}'"
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

# A download can outlast the idle timer, which would drop us into the
# screensaver right after the calendar is drawn.
keep_awake() {
	lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
}

allow_sleep() {
	lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
}

# UI processes that repaint the framebuffer (KUAL's "book cover", home grid, chrome).
# cvm = Java framework (older FW), mesquite = newer FW. Freeze whichever exists.
UI_PROCS="cvm mesquite"

lock_ui() {
	# Safe to block the screensaver: wait-exit reads raw input, so a power press
	# or tap still exits, and EXIT_TIMEOUT_MIN restores the UI regardless.
	lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
	lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
	for _p in ${UI_PROCS}; do
		if killall -STOP "${_p}" 2>/dev/null; then
			log "lock_ui: stopped ${_p}"
		fi
	done
}

unlock_ui() {
	for _p in ${UI_PROCS}; do
		killall -CONT "${_p}" 2>/dev/null
	done
	lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
	lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
	lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
}

kill_auto() {
	if [ -f "${CACHE}/auto.pid" ]; then
		_a=$(cat "${CACHE}/auto.pid" 2>/dev/null)
		[ -n "${_a}" ] && kill "${_a}" 2>/dev/null
		rm -f "${CACHE}/auto.pid"
	fi
	pkill -f "extensions/calendar/bin/auto" 2>/dev/null
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

# The waiter is the only thing that can un-freeze the framework, so callers
# must be able to check it really came up.
waiter_alive() {
	[ -f "${CACHE}/waiter.pid" ] || return 1
	_wp=$(cat "${CACHE}/waiter.pid" 2>/dev/null)
	[ -n "${_wp}" ] || return 1
	kill -0 "${_wp}" 2>/dev/null
}

# Try FBInk image flags used across builds; fall back to eips -g.
draw_png() {
	_img="$1"
	if [ -n "${FBINK}" ] && [ -f "${FBINK}" ]; then
		# w=0,h=0 scales to the full screen, so a PNG built for the wrong
		# resolution still covers the UI instead of cropping or leaving borders.
		if "${FBINK}" -g "file=${_img},w=0,h=0" -f >> "${LOG}" 2>&1; then
			return 0
		fi
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
		/usr/sbin/eips 2 3 "Falta ${VIEW}.png" 2>/dev/null
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

	# Detach so KUAL can close first, then paint. Painting before the menu is gone
	# lets the framework repaint its book cover on top of the calendar.
	(
		sleep 2
		log "display: start ${_path}"
		# Prove the image draws while the UI is still alive.
		if ! draw_png "${_path}"; then
			/usr/sbin/eips -c 2>/dev/null
			/usr/sbin/eips 2 3 "No se pudo dibujar" 2>/dev/null
			/usr/sbin/eips 2 5 "Ver cache/calendar.log" 2>/dev/null
			log "display: draw failed before lock"
			allow_sleep
			exit 1
		fi

		lock_ui
		# From here the framework is frozen and only unlock_ui can bring it
		# back, so never leave on a signal without releasing it.
		trap 'log "display: signal after lock"; unlock_ui; exit 1' HUP INT TERM
		if ! draw_png "${_path}"; then
			unlock_ui
			/usr/sbin/eips 2 3 "No se pudo dibujar" 2>/dev/null
			log "display: draw failed after lock"
			exit 1
		fi
		echo "1" > "${CACHE}/showing.pid"
		start_waiter
		sleep 1
		if ! waiter_alive; then
			# Nothing would watch for the exit tap: the UI would stay frozen
			# until the battery died.
			log "display: waiter did not start, unlocking"
			unlock_ui
			rm -f "${CACHE}/showing.pid" 2>/dev/null
			/usr/sbin/eips 2 3 "Error watcher, UI restaurada" 2>/dev/null
			exit 1
		fi
		log "display: ok ${_path}"

		# Late repaints (KUAL cover, home chrome) can land after our draw; overwrite them.
		for _d in 2 3 5; do
			sleep "${_d}"
			[ -f "${CACHE}/showing.pid" ] || exit 0
			[ -f "${CACHE}/STOP" ] && exit 0
			draw_png "${_path}" >/dev/null 2>&1
		done
		log "display: redraw pass done"
	) >/dev/null 2>&1 &
	return 0
}
