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
coexist() { # asm that must assemble under -isa=sh-jcore (proves SH-2 base + J-core coexist)
  if printf '\t%s\n' "$1" | "$AS" -isa=sh-jcore -o /tmp/rt.o - 2>/dev/null; then pass=$((pass+1)); else echo "FAIL[coexist]: $1 failed under -isa=sh-jcore"; fail=$((fail+1)); fi
}
gate() { # asm that must be REJECTED under the given real non-jcore arch
  local asm="$1" arch="$2"
  if printf '\t%s\n' "$asm" | "$AS" -isa="$arch" -o /tmp/rt.o - 2>/dev/null; then echo "FAIL[gate]: $asm assembled under -isa=$arch"; fail=$((fail+1)); else pass=$((pass+1)); fi
}
check   "cas.l r1,r2,@r0" "22 13"
check   "bgnd"             "00 3b"
coexist "mov r1,r2"
gate    "cas.l r1,r2,@r0" "sh2"
check   "stc pteh, r1"    "01 53"
check   "stc ptel, r1"    "01 63"
check   "stc asidr, r1"   "01 73"
check   "stc tsbptr, r1"  "01 43"
check   "ldtlb.rn"        "00 78"
# J-core coprocessor CP0/CPI (Phase 5)
check   "lds r3, cp0_com"        "43 88"
check   "sts cp0_com, r2"        "42 c8"
check   "clds cp0_r5, cp0_com"   "45 89"
check   "csts cp0_com, cp0_r6"   "46 c9"
check   "lds r3, cpi_com"        "43 5a"
check   "sts cpi_com, r2"        "02 5a"
check   "clds cpi_r5, cpi_com"   "f5 1d"
check   "csts cpi_com, cpi_r7"   "f7 0d"
gate    "clds cp0_r5, cp0_com" "sh2"
gate    "stc pteh, r1"    "sh2"
echo "----"; echo "GAS-RT pass $pass / fail $fail"; [ "$fail" -eq 0 ]
