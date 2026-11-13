#!/bin/sh
set -eu
mkdir -p /backups
name="/backups/carbondesk-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump --format=custom --file="$name.tmp"
mv "$name.tmp" "$name"
echo "Backup saved: $name"
