#!/bin/sh
# Syntax check dei moduli JS del frontend (eseguito in container node)
status=0
for f in /js/*.js; do
  if node --check "$f"; then
    echo "OK: $f"
  else
    status=1
  fi
done
exit $status
