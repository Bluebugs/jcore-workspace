#!/usr/bin/env bash
# SH PC-relative symbol fixup test: assemble @(sym,pc) forms with llvm-mc and
# verify the emitted SH ELF relocations via binutils sh-elf-objdump (which names
# them; LLVM has no SH reloc names). Expect R_SH_DIR8WPL (.l/mova) + R_SH_DIR8WPZ (.w).
set -euo pipefail
MC=${LLVM_MC:-llvm-project/build/bin/llvm-mc}
OBJDUMP=${OBJDUMP:-sh-elf-objdump}
o=$(mktemp /tmp/sh-fx.XXXX.o)
printf 'mov.l @(sym_l,pc), r1\nmova @(sym_m,pc), r0\nmov.w @(sym_w,pc), r2\n' \
  | "$MC" --arch=sh -filetype=obj -o "$o"
recs=$("$OBJDUMP" -r "$o" 2>/dev/null)
rm -f "$o"
echo "$recs"
wpl=$(echo "$recs" | grep -c 'R_SH_DIR8WPL' || true)
wpz=$(echo "$recs" | grep -c 'R_SH_DIR8WPZ' || true)
echo "--- R_SH_DIR8WPL=$wpl R_SH_DIR8WPZ=$wpz ---"
[ "$wpl" -eq 2 ] && [ "$wpz" -eq 1 ] && echo "RELOC OK" || { echo "RELOC FAIL"; exit 1; }
