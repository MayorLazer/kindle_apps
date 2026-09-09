#!/bin/sh
# Fetch one board PNG (calendar/today/weather/month), then display.
# Wi-Fi is enabled only for the download, then turned off. No background loop.
#
# Usage: update.sh [view]
# Note: stock Kindle BusyBox wget (1.17) cannot do HTTPS. For GitHub use
# curl (USBNet) or an http:// LAN URL (serve-http.ps1).

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config
set_view "${1:-calendar}"

_label=$(view_label)
/usr/sbin/eips 1 1 "actualizando ${_label}..." 2>/dev/null

if [ -z "${CALENDAR_URL}" ] || echo "${CALENDAR_URL}" | grep -q REPLACE; then
	/usr/sbin/eips -c 2>/dev/null
	/usr/sbin/eips 2 3 "Falta CALENDAR_URL" 2>/dev/null
	/usr/sbin/eips 2 5 "Edita bin/config" 2>/dev/null
	log "update: missing CALENDAR_URL"
	exit 1
fi

_url=$(url_for_view)

case "${_url}" in
	https://*)
		if [ -z "${CURL}" ] || [ ! -f "${CURL}" ]; then
			/usr/sbin/eips 2 3 "HTTPS: falta curl" 2>/dev/null
			/usr/sbin/eips 2 5 "USBNet curl o http://" 2>/dev/null
			log "update: https URL but no curl; BusyBox wget cannot SSL"
			_img=$(find_image)
			if [ -n "${_img}" ]; then
				/usr/sbin/eips 2 7 "Mostrando cache" 2>/dev/null
				sleep 1
				display_image "${_img}"
				exit 0
			fi
			/usr/sbin/eips 2 7 "Sin imagen" 2>/dev/null
			exit 1
		fi
		;;
esac

keep_awake

/usr/sbin/eips 1 2 "wifi..." 2>/dev/null
if ! wifi_on; then
	/usr/sbin/eips 2 3 "Sin Wi-Fi" 2>/dev/null
	log "update: wifi failed"
	# wifi_on already enabled the radio; leaving it on drains the battery
	# for days on a device that mostly sits idle.
	wifi_off
	if _img=$(find_image); then
		display_image "${_img}"
		exit 1
	fi
	if stay_awake_mode && [ -f "${CACHE}/showing.pid" ]; then
		after_display
	else
		allow_sleep
	fi
	exit 1
fi

_tmp="${CACHE}/download.png"
/usr/sbin/eips 1 2 "descargando..." 2>/dev/null
log "update: fetch ${_url}"

_ok=0
if download_url "${_url}" "${_tmp}"; then
	_sz=$(wc -c < "${_tmp}" 2>/dev/null | tr -cd '0-9')
	if [ -n "${_sz}" ] && [ "${_sz}" -gt 500 ] && is_png "${_tmp}" && png_complete "${_tmp}"; then
		mv "${_tmp}" "${IMG}"
		cp -f "${IMG}" "/mnt/us/documents/${VIEW}.png" 2>/dev/null
		log "update: ok view=${VIEW} bytes=${_sz}"
		_ok=1
	else
		log "update: rejected download bytes=${_sz:-0}"
		od -An -tx1 -N8 "${_tmp}" >> "${LOG}" 2>&1
		rm -f "${_tmp}"
	fi
fi
wifi_off

if [ "${_ok}" = "1" ]; then
	/usr/sbin/eips 1 2 "mostrando..." 2>/dev/null
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
case "${_url}" in
	https://*)
		/usr/sbin/eips 2 7 "Pon curl o http://" 2>/dev/null
		;;
esac
if stay_awake_mode && [ -f "${CACHE}/showing.pid" ]; then
	after_display
else
	allow_sleep
fi
exit 1
