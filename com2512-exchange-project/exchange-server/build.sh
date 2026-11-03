#!/usr/bin/env bash
# Build the Phase 1 test server into a single runnable jar.
#
#   ./build.sh            -> dist/xchg-server.jar
#
# Needs a JDK 17+ on PATH and nothing else: no Maven, no Gradle, no network,
# no third-party jars. Ship dist/xchg-server.jar to students and keep src/.
set -euo pipefail
cd "$(dirname "$0")"

OUT=build/classes
DIST=dist
MAIN=com.com2512.xchg.Main

command -v javac >/dev/null || { echo "javac not found: install a JDK 17 or newer" >&2; exit 1; }

javac -version 2>/dev/null || javac -version
rm -rf "$OUT" "$DIST"
mkdir -p "$OUT" "$DIST"

# -Xlint:all keeps the source honest; the kit should compile clean.
javac -Xlint:all -d "$OUT" $(find src -name '*.java')

# The UI page travels inside the jar, so the binary is genuinely self-contained.
cp -r resources/ui "$OUT/ui"

jar --create --file "$DIST/xchg-server.jar" --main-class "$MAIN" -C "$OUT" .

echo
echo "built $DIST/xchg-server.jar"
java -jar "$DIST/xchg-server.jar" --selftest
echo
echo "ship this to students:   $DIST/xchg-server.jar"
echo "they run:                java -jar xchg-server.jar"
