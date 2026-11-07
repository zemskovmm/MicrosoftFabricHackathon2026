#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ ! -x .venv/bin/inventorypulse ]]; then
  echo 'Please install Python 3.11+ and follow the README setup steps first.'
  exit 1
fi
.venv/bin/inventorypulse run
.venv/bin/inventorypulse serve
