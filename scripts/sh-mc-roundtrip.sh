#!/usr/bin/env bash
# 3-way SH instruction round-trip: insns.json <-> llvm-mc <-> sh-elf-objdump.
# Usage: sh-mc-roundtrip.sh "<asm>" "<expected-hex-bytes-big-endian>"
#   e.g. sh-mc-roundtrip.sh "mov r2,r1" "61 23"
set -euo pipefail
LLVM_MC="${LLVM_MC:-llvm-project/build/bin/llvm-mc}"
OBJDUMP="${OBJDUMP:-sh-elf-objdump}"
ASM="$1"; EXPECT="$2"

# 1. llvm-mc -> encoding bytes (e.g. "0x61,0x23")
enc=$("$LLVM_MC" --arch=sh -show-encoding <<<"$ASM" \
  | sed -n 's/.*encoding: \[\(.*\)\].*/\1/p' | tr ',' ' ' | sed 's/0x//g')
got=$(echo $enc | tr 'A-F' 'a-f')
want=$(echo "$EXPECT" | tr 'A-F' 'a-f')
if [ "$got" != "$want" ]; then
  echo "FAIL[bytes]: asm='$ASM' llvm=[$got] insns.json=[$want]"; exit 1
fi

# 2. cross-disassemble the bytes with binutils objdump (big-endian SH)
tmp=$(mktemp /tmp/sh-rt.XXXX.bin)
printf "$(printf '\\x%s' $got)" > "$tmp"
dis=$("$OBJDUMP" -b binary -m sh -EB -D "$tmp" 2>/dev/null \
  | awk -F'\t' 'NF>=3 && $1 ~ /:$/ {print $3"\t"$4; exit}')
rm -f "$tmp"
mnem=$(echo "$dis" | cut -f1)
want_mnem=$(echo "$ASM" | awk '{print $1}')
if [ "$mnem" != "$want_mnem" ]; then
  echo "FAIL[objdump]: asm='$ASM' bytes=[$got] objdump='$dis' (mnem '$mnem' != '$want_mnem')"; exit 1
fi
echo "PASS: '$ASM' -> [$got] -> objdump '$dis'"
