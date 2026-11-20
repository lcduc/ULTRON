#!/bin/sh
# Starts ntfy with one provisioned user that may use only the one private topic.
# User, password, topic and token come from the environment (compose/.env); the user,
# its access and the token are re-created from them on every start.
set -e
: "${NTFY_USER:?}" "${NTFY_PASSWORD:?}" "${NTFY_TOPIC:?}"
# `ntfy user hash` asks for the password twice; the hash is its last output line.
HASH=$(printf '%s\n%s\n' "$NTFY_PASSWORD" "$NTFY_PASSWORD" | ntfy user hash 2>/dev/null | tail -n 1 | tr -d '\r')
unset NTFY_PASSWORD
export NTFY_AUTH_USERS="$NTFY_USER:$HASH:user"
export NTFY_AUTH_ACCESS="$NTFY_USER:$NTFY_TOPIC:read-write"
exec ntfy serve
