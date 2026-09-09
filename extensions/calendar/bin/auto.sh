#!/bin/sh
# Keep the board on screen and refresh it every AUTO_REFRESH_MIN minutes.
# Tablero menu entries launch this directly: download, show, stay awake,
# then re-fetch on a timer until you tap or Salir.
#
# Quiet hours (QUIET_START_HOUR .. QUIET_END_HOUR) skip the Wi-Fi download
# and keep the cached board on screen — no overnight radio wakeups.
#
# It only runs while the board is actually displayed: as soon as you exit
# the view (tap, KUAL Salir) the loop stops. That way it can never
# re-freeze the framework while you are reading a book.
#
# Timers do not advance while the Kindle is suspended, so a refresh lands on
# wake rather than exactly on the interval. Each refresh turns Wi-Fi on and
# off again, which costs battery: keep the interval long.

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

# KUAL: auto.sh today   |   child: auto.sh --child today
if [ "$1" = "--child" ]; then
	set_view "${2:-calendar}"
else
	set_view "${1:-calendar}"
	if command -v nohup >/dev/null 2>&1; then
		nohup /bin/sh "${BIN}/auto.sh" --child "${VIEW}" >> "${LOG}" 2>&1 &
	else
		/bin/sh "${BIN}/auto.sh" --child "${VIEW}" >> "${LOG}" 2>&1 &
	fi
	log "auto: detached child view=${VIEW}"
	exit 0
fi

# Only one loop at a time.
if [ -f "${CACHE}/auto.pid" ]; then
	_old=$(cat "${CACHE}/auto.pid" 2>/dev/null)
	if [ -n "${_old}" ] && kill -0 "${_old}" 2>/dev/null; then
		kill "${_old}" 2>/dev/null
		log "auto: replaced previous loop pid=${_old}"
	fi
fi

echo $$ > "${CACHE}/auto.pid"
trap 'rm -f "${CACHE}/auto.pid" "${CACHE}/stay_awake" 2>/dev/null; log "auto: signal, stopping"; exit 0' HUP INT TERM
export STAY_AWAKE=1
echo "1" > "${CACHE}/stay_awake"
log "auto: start view=${VIEW} every ${AUTO_REFRESH_MIN}min quiet=${QUIET_START_HOUR}-${QUIET_END_HOUR} (stay awake)"

if in_quiet_hours; then
	log "auto: quiet hours, show cache only"
	/bin/sh "${BIN}/show.sh" "${VIEW}"
else
	/bin/sh "${BIN}/update.sh" "${VIEW}"
fi

# display_image paints from a background subshell, so the view takes a few
# seconds to register. Without this wait the loop would quit immediately.
_wait=0
while [ "${_wait}" -lt 30 ]; do
	[ -f "${CACHE}/showing.pid" ] && break
	sleep 2
	_wait=$((_wait + 2))
done
if [ ! -f "${CACHE}/showing.pid" ]; then
	log "auto: nothing on screen, stopping"
	rm -f "${CACHE}/auto.pid" "${CACHE}/stay_awake" 2>/dev/null
	exit 1
fi

_interval=$((AUTO_REFRESH_MIN * 60))
while :; do
	_slept=0
	while [ "${_slept}" -lt "${_interval}" ]; do
		sleep 10
		_slept=$((_slept + 10))
		if [ ! -f "${CACHE}/showing.pid" ] || [ -f "${CACHE}/STOP" ]; then
			log "auto: view closed, stopping"
			rm -f "${CACHE}/auto.pid" "${CACHE}/stay_awake" 2>/dev/null
			exit 0
		fi
		# powerd forgets preventScreenSaver; re-assert often while Auto is up.
		hold_awake_tick
	done
	if in_quiet_hours; then
		log "auto: quiet hours, skip Wi-Fi refresh"
		# Refresh the on-device footer (battery) without touching the network.
		redraw_showing
		continue
	fi
	log "auto: refresh view=${VIEW}"
	/bin/sh "${BIN}/update.sh" "${VIEW}"
done
