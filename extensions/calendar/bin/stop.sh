#!/bin/sh
# Exit calendar / restore Kindle UI.

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

touch "${CACHE}/STOP" 2>/dev/null
kill_waite
unlock_ui
rm -f "${CACHE}/showing.pid" "${CACHE}/STOP" "${CACHE}/exit.reason" 2>/dev/null

/usr/sbin/eips -c 2>/dev/null
/usr/sbin/eips 8 10 "Calendario cerrado" 2>/dev/null
if [ -n "${FBINK}" ] && [ -f "${FBINK}" ]; then
	"${FBINK}" -q -c -f 2>/dev/null
	"${FBINK}" -q -m -y 18 "Calendario cerrado" 2>/dev/null
	"${FBINK}" -q -m -y 20 "Home restaurado" 2>/dev/null
fi
log "stop"
exit 0
