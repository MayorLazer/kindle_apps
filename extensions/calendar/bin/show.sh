#!/bin/sh
# Show cached calendar.png (no network).

EXT="/mnt/us/extensions/calendar"
# shellcheck disable=SC1091
. "${EXT}/bin/lib.sh"
load_config

/usr/sbin/eips 1 1 "calendario..." 2>/dev/null

_img=$(find_image)
if [ -z "${_img}" ]; then
	/usr/sbin/eips -c 2>/dev/null
	/usr/sbin/eips 2 3 "Falta calendar.png" 2>/dev/null
	/usr/sbin/eips 2 5 "Usa Actualizar y mostrar" 2>/dev/null
	exit 1
fi

display_image "${_img}"
exit 0
