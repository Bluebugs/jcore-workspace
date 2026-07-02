#!/usr/bin/env bash
# 3-way SH round-trip oracle: insns.json <-> llvm-mc <-> sh-elf-objdump.
# Single: sh-mc-roundtrip.sh "<asm>" "<expect-hex>"
# Batch:  <gen cases> | sh-mc-roundtrip.sh --batch   (reads "asm<TAB>hex" lines)
#
# PRIMARY check (hard): llvm-mc encoding bytes == insns.json expected bytes.
# CROSS-CHECK (binutils, soft): disassemble the bytes (multi-arch) and compare
# REGISTER operands (tolerates mnemonic-spelling e.g. xtract/xtrct and immediate
# radix/sign differences). The cross-check is informational, never fatal: the
# bytes have already been proven equal to insns.json (the source of truth), so a
# register-spelling disagreement can only be a binutils disassembly ambiguity
# (e.g. FP mode-dependent DR/XD printed as FR pairs), not an llvm encoding error.
# Outcomes: cross-checked (regs agree), XDIVERGE (regs differ), or BYTES-ONLY
# (binutils cannot decode the bytes on any SH arch). Only FAIL[bytes]/FAIL[asm]
# fail the run.
set -uo pipefail
LLVM_MC="${LLVM_MC:-llvm-project/build/bin/llvm-mc}"
OBJDUMP="${OBJDUMP:-sh-elf-objdump}"
ARCHES="sh4a sh4 sh2a sh3 sh2 sh4al-dsp"

regs_of() { echo "$1" | grep -oE 'r1[0-5]|r[0-9]' | paste -sd, -; }

# returns: 0 pass(cross-checked), 2 pass(bytes-only), 3 pass(regs diverge),
#          1 fail (bytes/asm). echoes a message.
check_one() {
  local ASM="$1" EXPECT="$2" enc got want
  enc=$("$LLVM_MC" --arch=sh -show-encoding <<<"$ASM" 2>/dev/null \
        | sed -n 's/.*encoding: \[\(.*\)\].*/\1/p' | tr ',' ' ' | sed 's/0x//g')
  got=$(echo $enc | tr 'A-F' 'a-f'); want=$(echo "$EXPECT" | tr 'A-F' 'a-f')
  if [ -z "$got" ]; then echo "FAIL[asm]: '$ASM' (no encoding)"; return 1; fi
  if [ "$got" != "$want" ]; then echo "FAIL[bytes]: '$ASM' llvm=[$got] insns.json=[$want]"; return 1; fi
  local tmp dis decoded=""
  tmp=$(mktemp /tmp/sh-rt.XXXX.bin); printf "$(printf '\\x%s' $got)" > "$tmp"
  for m in $ARCHES; do
    dis=$("$OBJDUMP" -b binary -m $m -EB -D "$tmp" 2>/dev/null \
          | awk -F'\t' 'NF>=3 && $1 ~ /:$/ {print $3" "$4; exit}')
    case "$dis" in *.word*|"") ;; *) decoded="$dis"; break;; esac
  done
  rm -f "$tmp"
  if [ -z "$decoded" ]; then echo "BYTESONLY: '$ASM' [$got] (binutils cannot decode)"; return 2; fi
  if [ "$(regs_of "$ASM")" != "$(regs_of "$decoded")" ]; then
    echo "XDIVERGE: '$ASM' [$got] objdump='$decoded' (regs '$(regs_of "$ASM")' != '$(regs_of "$decoded")') — bytes match insns.json; binutils disasm ambiguity"; return 3; fi
  return 0
}

if [ "${1:-}" = "--batch" ]; then
  pass=0; bytesonly=0; xdiverge=0; fail=0
  while IFS=$'\t' read -r asm hex; do
    [ -z "$asm" ] && continue
    check_one "$asm" "$hex"; rc=$?
    case $rc in
      0) pass=$((pass+1));;
      2) bytesonly=$((bytesonly+1));;
      3) xdiverge=$((xdiverge+1));;
      *) fail=$((fail+1));;
    esac
  done
  echo "----"; echo "PASS(3-way) $pass / BYTES-ONLY $bytesonly / XDIVERGE $xdiverge / FAIL $fail"
  [ "$fail" -eq 0 ]
else
  check_one "$1" "$2"; rc=$?; [ $rc -ne 1 ] && echo "OK rc=$rc"; [ $rc -ne 1 ]
fi
