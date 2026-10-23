#!/bin/bash
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/osascript -l JavaScript "$here/HubICG-Station-UI.js" "$here" "$@"
