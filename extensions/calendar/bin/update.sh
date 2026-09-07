#!/bin/sh
# Fetch latest calendar.png from GitHub Pages (or any URL), then display.
# Wi-Fi is enabled only for the download, then turned off. No background loop.

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

/usr/sbin/eips 1 1 "actualizando..." 2>/dev/null

if [ -z "${CALENDAR_URL}" ] || echo "${CALENDAR_URL}" | grep -q REPLACE; then
	/usr/sbin/eips -c 2>/dev/null
	/usr/sbin/eips 2 3 "Falta CALENDAR_URL" 2>/dev/null
	/usr/sbin/eips 2 5 "Edita bin/config" 2>/dev/null
	log "update: missing CALENDAR_URL"
	exit 1
fi

if ! wifi_on; then
	/usr/sbin/eips 2 3 "Sin Wi-Fi" 2>/dev/null
	log "update: wifi failed"
	# still try to show cache
	_img=$(find_image) && display_image "${_img}"
	exit 1
fi

_tmp="${CACHE}/download.png"
_flags="-q -T 45 -O"
if [ "${WGET_INSECURE}" = "1" ]; then
	_flags="-q -T 45 --no-check-certificate -O"
fi

# shellcheck disable=SC2086
if wget ${_flags} "${_tmp}" "${CALENDAR_URL}" 2>/dev/null \
	&& [ -s "${_tmp}" ]; then
	_sz=$(wc -c < "${_tmp}" 2>/dev/null | tr -cd '0-9')
	if [ -n "${_sz}" ] && [ "${_sz}" -gt 500 ]; then
		mv "${_tmp}" "${IMG}"
		cp -f "${IMG}" /mnt/us/documents/calendar.png 2>/dev/null
		log "update: ok bytes=${_sz}"
		_ok=1
	else
		log "update: file too small"
		rm -f "${_tmp}"
		_ok=0
	fi
else
	log "update: wget failed"
	_ok=0
	rm -f "${_tmp}"
fi
wifi_off

if [ "${_ok}" = "1" ]; then
	display_image "${IMG}"
	exit 0
fi

/usr/sbin/eips 2 3 "Download fallo" 2>/dev/null
_img=$(find_image)
if [ -n "${_img}" ]; then
	/usr/sbin/eips 2 5 "Mostrando cache" 2>/dev/null
	sleep 1
	display_image "${_img}"
	exit 0
fi

/usr/sbin/eips 2 5 "Sin imagen" 2>/dev/null
exit 1
