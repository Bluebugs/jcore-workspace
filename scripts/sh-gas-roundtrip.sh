#!/usr/bin/env bash
# Build (if needed) the jcore-branch gas and round-trip the J-core delta insns.
set -uo pipefail
ROOT=/home/cedric/work/jcore/jcore-workspace
BU="$ROOT/binutils-gdb"
AS="$BU/build-sh/gas/as-new"
OD=${SH_OD:-sh-elf-objdump}
if [ ! -x "$AS" ]; then
  echo "building gas..."; ( cd "$BU" && mkdir -p build-sh && cd build-sh \
    && ../configure --target=sh-elf --disable-gdb --disable-ld --disable-sim --disable-gprof --disable-werror >/tmp/cfg.log 2>&1 \
    && make all-gas -j"$(nproc)" >/tmp/mk.log 2>&1 ) || { echo "BUILD FAIL"; exit 1; }
fi
pass=0; fail=0
check() { # asm  want-hex
  local asm="$1" want="$2" got
  printf '\t%s\n' "$asm" | "$AS" -isa=sh-jcore -o /tmp/rt.o - 2>/tmp/rt.err || { echo "FAIL[asm]: $asm"; cat /tmp/rt.err; fail=$((fail+1)); return; }
  got=$("$OD" -s -j .text /tmp/rt.o 2>/dev/null | grep -E '^ [0-9a-f]{4} ' | awk '{print $2}' | head -1 | sed 's/\(..\)\(..\).*/\1 \2/')
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else echo "FAIL[bytes]: $asm got[$got] want[$want]"; fail=$((fail+1)); fi
}
gate() { # asm that must NOT assemble without -isa
  if printf '\t%s\n' "$1" | "$AS" -o /tmp/rt.o - 2>/dev/null; then echo "FAIL[gate]: $1 assembled without -isa=sh-jcore"; fail=$((fail+1)); else pass=$((pass+1)); fi
}
check "cas.l r1,r2,@r0" "22 13"
check "bgnd"            "00 3b"
gate  "bgnd"
echo "----"; echo "GAS-RT pass $pass / fail $fail"; [ "$fail" -eq 0 ]
