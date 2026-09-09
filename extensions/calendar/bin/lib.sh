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
	# Auto skips Wi-Fi refresh in this local-hour window [start, end).
	: "${QUIET_START_HOUR:=0}"
	: "${QUIET_END_HOUR:=7}"
	# Match schedule png_rotate so the status stamp sits on the footer edge.
	: "${PNG_ROTATE:=90}"
	# Optional path to KOReader statistics.sqlite3 (auto-discovered if empty).
	: "${KOREADER_STATS_DB:=}"
	FBINK=$(echo "${FBINK}" | tr -d '\r')
	CALENDAR_URL=$(echo "${CALENDAR_URL}" | tr -d '\r')
	CURL=$(echo "${CURL}" | tr -d '\r')
	CALENDAR_TOKEN=$(echo "${CALENDAR_TOKEN}" | tr -d '\r')
	KOREADER_STATS_DB=$(echo "${KOREADER_STATS_DB}" | tr -d '\r')
	PNG_ROTATE=$(echo "${PNG_ROTATE}" | tr -d '\r')
	QUIET_START_HOUR=$(echo "${QUIET_START_HOUR}" | tr -d '\r')
	QUIET_END_HOUR=$(echo "${QUIET_END_HOUR}" | tr -d '\r')

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
		calendar|today|weather|month|weekly) ;;
		*) VIEW="calendar" ;;
	esac
	IMG="${EXT}/${VIEW}.png"
}

view_label() {
	case "${VIEW}" in
		today) echo "hoy" ;;
		weather) echo "clima" ;;
		month) echo "mes" ;;
		weekly) echo "semanal" ;;
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

# Hold off the idle screensaver only while Wi-Fi / drawing is in progress,
# or for the whole Auto session (STAY_AWAKE=1 / cache/stay_awake).
keep_awake() {
	lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
}

allow_sleep() {
	lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
}

stay_awake_mode() {
	[ "${STAY_AWAKE}" = "1" ] && return 0
	[ -f "${CACHE}/stay_awake" ] && return 0
	return 1
}

# After the board is painted: Auto keeps the screensaver off; one-shot show
# lets the stock idle timeout and power button sleep as usual.
after_display() {
	if stay_awake_mode; then
		echo "1" > "${CACHE}/stay_awake"
		keep_awake
		lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
		log "after_display: stay awake (auto)"
	else
		rm -f "${CACHE}/stay_awake" 2>/dev/null
		allow_sleep
		# One-shot: allow the stock screensaver again now that painting is done.
		lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
		log "after_display: screensaver allowed"
	fi
}

# UI processes that repaint the framebuffer (KUAL's "book cover", home grid, chrome).
# cvm = Java framework (older FW), mesquite = newer FW. Freeze whichever exists.
# Do not STOP pillow: that is the screensaver compositor.
UI_PROCS="cvm mesquite"

lock_ui() {
	# Freeze home so it cannot paint over the board. Hold pillow off while we
	# own the framebuffer; after_display re-enables it for one-shot show so the
	# stock screensaver can still run.
	for _p in ${UI_PROCS}; do
		if killall -STOP "${_p}" 2>/dev/null; then
			log "lock_ui: stopped ${_p}"
		fi
	done
	lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
}

unlock_ui() {
	for _p in ${UI_PROCS}; do
		killall -CONT "${_p}" 2>/dev/null
	done
	if stay_awake_mode; then
		# Auto refresh may kill an old display painter; do not release sleep
		# hold or jump to Home over the board.
		keep_awake
		lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
		log "unlock_ui: stay-awake, skip Home"
		return 0
	fi
	allow_sleep
	lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
	lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
}

restore_home() {
	for _p in ${UI_PROCS}; do
		killall -CONT "${_p}" 2>/dev/null
	done
	allow_sleep
	lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
	lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
}

in_screensaver() {
	_st=$(lipc-get-prop com.lab126.powerd state 2>/dev/null || echo "")
	case "${_st}" in
		ScreenSaver|ReadyToSuspend|Suspended) return 0 ;;
	esac
	return 1
}

redraw_showing() {
	_img=$(cat "${CACHE}/showing.path" 2>/dev/null)
	[ -n "${_img}" ] && [ -f "${_img}" ] || return 0
	log "redraw: ${_img}"
	if stay_awake_mode; then
		keep_awake
		lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
	fi
	draw_png "${_img}" clear >/dev/null 2>&1
	stamp_status
}

# powerd sometimes drops preventScreenSaver; Auto must poke it regularly.
hold_awake_tick() {
	stay_awake_mode || return 0
	keep_awake
	lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
}

# --- On-device footer status (battery / Wi-Fi / last refresh / KOReader) ---

battery_pct() {
	_b=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null | tr -cd '0-9')
	if [ -n "${_b}" ]; then
		echo "${_b}"
		return 0
	fi
	for _f in \
		/sys/devices/system/yoshi_battery/yoshi_battery0/battery_capacity \
		/sys/class/power_supply/battery/capacity; do
		if [ -f "${_f}" ]; then
			tr -cd '0-9' < "${_f}"
			return 0
		fi
	done
	echo ""
}

wifi_label() {
	_en=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null | tr -cd '0-9')
	if [ "${_en}" = "0" ]; then
		echo "WiFi off"
		return 0
	fi
	_st=$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null || echo "")
	case "${_st}" in
		CONNECTED|CONNECTED_PENDING) echo "WiFi on" ;;
		*) echo "WiFi ..." ;;
	esac
}

mark_refreshed() {
	date +"%H:%M" > "${CACHE}/last_refresh.txt" 2>/dev/null
}

last_refresh_label() {
	if [ -f "${CACHE}/last_refresh.txt" ]; then
		_t=$(tr -d '\r\n' < "${CACHE}/last_refresh.txt")
		[ -n "${_t}" ] && echo "Act ${_t}" && return 0
	fi
	echo "Act --:--"
}

find_koreader_db() {
	if [ -n "${KOREADER_STATS_DB}" ] && [ -f "${KOREADER_STATS_DB}" ]; then
		echo "${KOREADER_STATS_DB}"
		return 0
	fi
	for _d in \
		/mnt/us/koreader/settings/statistics.sqlite3 \
		/mnt/us/.adds/koreader/settings/statistics.sqlite3 \
		/mnt/us/koreader/statistics.sqlite3 \
		/mnt/us/.adds/koreader/statistics.sqlite3; do
		if [ -f "${_d}" ]; then
			echo "${_d}"
			return 0
		fi
	done
	return 1
}

find_sqlite3() {
	for _c in sqlite3 /mnt/us/usbnet/bin/sqlite3 /mnt/us/libkh/bin/sqlite3; do
		if command -v "${_c}" >/dev/null 2>&1 || [ -x "${_c}" ]; then
			echo "${_c}"
			return 0
		fi
	done
	return 1
}

# Consecutive local days with KOReader reading time (needs sqlite3 on device).
# Must stay fast: a locked/huge DB must never block display startup.
koreader_streak() {
	_sql=$(find_sqlite3) || return 1
	_db=$(find_koreader_db) || return 1
	_today=$(date +%Y-%m-%d)
	# Single short query; busy timeout so a locked DB cannot hang Auto.
	_list=$(
		"${_sql}" -bail -cmd ".timeout 200" "${_db}" \
			"SELECT DISTINCT date(start_time,'unixepoch','localtime') AS d FROM page_stat_data WHERE duration>0 ORDER BY d DESC LIMIT 40;" \
			2>/dev/null
	) || true
	if [ -z "${_list}" ]; then
		_list=$(
			"${_sql}" -bail -cmd ".timeout 200" "${_db}" \
				"SELECT DISTINCT date(start_time,'unixepoch','localtime') AS d FROM page_stat WHERE duration>0 ORDER BY d DESC LIMIT 40;" \
				2>/dev/null
		) || true
	fi
	[ -n "${_list}" ] || return 1
	_n=$(printf '%s\n' "${_list}" | awk -v today="${_today}" '
		function jul(s,   x,y,m,d) {
			split(s, x, "-"); y = x[1] + 0; m = x[2] + 0; d = x[3] + 0
			if (m <= 2) { y--; m += 12 }
			return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d
		}
		BEGIN { n = 0; prev = "" }
		NF {
			if (n == 0) {
				if ($1 != today && jul(today) - jul($1) != 1) exit
				n = 1; prev = $1; next
			}
			if (jul(prev) - jul($1) != 1) exit
			n++; prev = $1
		}
		END { if (n > 0) print n }
	')
	[ -n "${_n}" ] && [ "${_n}" -gt 0 ] && echo "${_n}"
}

status_line() {
	_bits=""
	_b=$(battery_pct)
	[ -n "${_b}" ] && _bits="${_bits}Bat ${_b}%"
	_w=$(wifi_label)
	[ -n "${_w}" ] && _bits="${_bits}  ${_w}"
	_a=$(last_refresh_label)
	[ -n "${_a}" ] && _bits="${_bits}  ${_a}"
	# Optional: only when KOREADER_STATS_DB is set, so a bad sqlite never
	# blocks board startup for everyone.
	if [ -n "${KOREADER_STATS_DB}" ]; then
		_k=$(koreader_streak 2>/dev/null || true)
		[ -n "${_k}" ] && _bits="${_bits}  KO ${_k}d"
	fi
	echo "${_bits}" | sed 's/^ *//'
}

stamp_status() {
	# Blit pre-rotated glyphs into the PNG footer band (same strip as SALIR).
	# Plain fbink text follows portrait axes and lands on the visual *side*
	# of a landscape board — do not fall back to that.
	[ -n "${FBINK}" ] && [ -f "${FBINK}" ] || return 0
	_line=$(status_line 2>/dev/null) || _line=""
	[ -n "${_line}" ] || return 0
	log "status: ${_line}"

	_glyphs="${BIN}/glyphs"
	_layout="${_glyphs}/layout.txt"
	_widths="${_glyphs}/widths.txt"
	[ -f "${_layout}" ] || {
		log "status: missing glyphs/layout.txt"
		return 0
	}

	_px=$(sed -n 's/^px=//p' "${_layout}" | head -1 | tr -cd '0-9')
	[ -n "${_px}" ] || {
		log "status: bad glyphs layout"
		return 0
	}

	# Landscape x along the footer; portrait y = 1024 - lx - glyph_advance.
	_lx=10
	_land_w=1024
	_i=0
	_len=${#_line}
	while [ "${_i}" -lt "${_len}" ]; do
		_i=$((_i + 1))
		_ch=$(printf '%s' "${_line}" | cut -c "${_i}-${_i}")
		_code=$(printf '%02X' "'${_ch}")
		_adv=8
		if [ -f "${_widths}" ]; then
			_w=$(awk -v c="${_code}" '$1 == c { print $2; exit }' "${_widths}")
			[ -n "${_w}" ] && _adv="${_w}"
		fi
		_g="${_glyphs}/${_code}.png"
		_py=$((_land_w - _lx - _adv))
		if [ "${_py}" -lt 0 ]; then
			break
		fi
		if [ -f "${_g}" ]; then
			"${FBINK}" -q -g "file=${_g},x=${_px},y=${_py}" >> "${LOG}" 2>&1
		fi
		_lx=$((_lx + _adv))
	done
	return 0
}

in_quiet_hours() {
	_h=$(date +%H | tr -cd '0-9')
	[ -n "${_h}" ] || return 1
	_h=$((_h + 0))
	_qs=$((QUIET_START_HOUR + 0))
	_qe=$((QUIET_END_HOUR + 0))
	# Disabled when start == end.
	[ "${_qs}" -eq "${_qe}" ] && return 1
	if [ "${_qs}" -lt "${_qe}" ]; then
		[ "${_h}" -ge "${_qs}" ] && [ "${_h}" -lt "${_qe}" ]
	else
		# Window wraps midnight, e.g. 22..7
		[ "${_h}" -ge "${_qs}" ] || [ "${_h}" -lt "${_qe}" ]
	fi
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
# Pass "clear" as $2 to wipe the framebuffer first — needed after KUAL/home
# have painted, or e-ink leaves the right strip looking blank on redraws.
draw_png() {
	_img="$1"
	_clear="${2:-}"
	if [ -n "${FBINK}" ] && [ -f "${FBINK}" ]; then
		if [ "${_clear}" = "clear" ]; then
			"${FBINK}" -q -c -f >> "${LOG}" 2>&1
		fi
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
	if [ "${_clear}" = "clear" ]; then
		/usr/sbin/eips -c 2>/dev/null
	fi
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
	# Ignore HUP: update.sh/show.sh exit right after launching us; a HUP would
	# otherwise run unlock_ui → allow_sleep and the screensaver would win.
	if [ -f "${CACHE}/display.pid" ]; then
		_oldd=$(cat "${CACHE}/display.pid" 2>/dev/null)
		[ -n "${_oldd}" ] && kill "${_oldd}" 2>/dev/null
		rm -f "${CACHE}/display.pid"
	fi
	(
		trap '' HUP
		echo $$ > "${CACHE}/display.pid"
		keep_awake
		if stay_awake_mode; then
			lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
		fi
		sleep 2
		log "display: start ${_path}"

		lock_ui
		# INT/TERM still restore the UI; HUP is ignored on purpose.
		trap 'log "display: signal after lock"; rm -f "${CACHE}/display.pid"; unlock_ui; exit 1' INT TERM

		# Clear + full flash so a previous home/KUAL paint cannot leave the
		# sidebar (right strip on Semanal) looking blank after redraws.
		if ! draw_png "${_path}" clear; then
			rm -f "${CACHE}/display.pid"
			unlock_ui
			/usr/sbin/eips 2 3 "No se pudo dibujar" 2>/dev/null
			/usr/sbin/eips 2 5 "Ver cache/calendar.log" 2>/dev/null
			log "display: draw failed after lock"
			exit 1
		fi
		# Mark showing BEFORE footer stamp. stamp_status used to run first and
		# could hang (sqlite / fbink -e), so Auto never saw showing.pid and
		# quit — Semanal looked like it "didn't start".
		echo "${_path}" > "${CACHE}/showing.path"
		echo "1" > "${CACHE}/showing.pid"
		start_waiter
		stamp_status
		sleep 1
		if ! waiter_alive; then
			# Nothing would watch for the exit tap: the UI would stay frozen
			# until the battery died.
			log "display: waiter did not start, unlocking"
			rm -f "${CACHE}/display.pid" "${CACHE}/showing.pid" "${CACHE}/showing.path" 2>/dev/null
			unlock_ui
			/usr/sbin/eips 2 3 "Error watcher, UI restaurada" 2>/dev/null
			exit 1
		fi
		log "display: ok ${_path}"

		# One delayed clear+paint catches late KUAL/home chrome. Multiple
		# flashes without a clear were blanking Semanal's light sidebar.
		sleep 4
		if [ -f "${CACHE}/showing.pid" ] && [ ! -f "${CACHE}/STOP" ]; then
			draw_png "${_path}" clear >/dev/null 2>&1
			stamp_status
			log "display: final clear redraw done"
		fi
		after_display
		# Stay resident so Auto's keep_awake tick overlaps; powerd is also
		# re-asserted by auto.sh every 10s while showing.
		if stay_awake_mode; then
			_i=0
			while [ "${_i}" -lt 60 ]; do
				[ -f "${CACHE}/showing.pid" ] || break
				[ -f "${CACHE}/STOP" ] && break
				# Replaced by a newer display painter.
				_cur=$(cat "${CACHE}/display.pid" 2>/dev/null)
				[ "${_cur}" = "$$" ] || break
				hold_awake_tick
				sleep 10
				_i=$((_i + 1))
			done
		fi
		rm -f "${CACHE}/display.pid" 2>/dev/null
	) >/dev/null 2>&1 &
	return 0
}
