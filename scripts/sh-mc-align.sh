#!/usr/bin/env bash
# SH PC-relative .l alignment: bare `mov.l L,r1` at a 2-mod-4 instruction address.
# SH .l PC base is (P+4)&~3, so the encoded disp depends on alignment. binutils
# (sh-elf-as) is the oracle; llvm-mc must produce identical .text bytes.
set -uo pipefail
MC=${LLVM_MC:-llvm-project/build/bin/llvm-mc}
prog=$'\tmov\tr0, r0\n\tmov.l\tL, r1\n\t.align 2\nL:\t.long 0x12345678\n'
echo "$prog" | sh-elf-as -o /tmp/al-gas.o - 2>/dev/null
gas=$(sh-elf-objdump -d /tmp/al-gas.o 2>/dev/null | sed -n 's/^[[:space:]]*[0-9a-f]*:[[:space:]]*\([0-9a-f][0-9a-f] [0-9a-f][0-9a-f]\).*/\1/p' | head -2 | tr '\n' '|')
echo "$prog" | "$MC" --arch=sh -filetype=obj -o /tmp/al-mc.o 2>/dev/null
mc=$(sh-elf-objdump -d /tmp/al-mc.o 2>/dev/null | sed -n 's/^[[:space:]]*[0-9a-f]*:[[:space:]]*\([0-9a-f][0-9a-f] [0-9a-f][0-9a-f]\).*/\1/p' | head -2 | tr '\n' '|')
rm -f /tmp/al-gas.o /tmp/al-mc.o
echo "gas:     $gas"; echo "llvm-mc: $mc"
[ -n "$gas" ] && [ "$gas" = "$mc" ] && echo "ALIGN OK (matches binutils)" || { echo "ALIGN FAIL"; exit 1; }
