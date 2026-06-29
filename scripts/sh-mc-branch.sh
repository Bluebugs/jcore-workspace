#!/usr/bin/env bash
# Assemble PC-relative branches to local labels with both llvm-mc and sh-elf-as;
# assert the resolved .text bytes are byte-identical.
# Also checks reloc types for bra (4) and bt (3).
set -uo pipefail
MC=${LLVM_MC:-llvm-project/build/bin/llvm-mc}
AS=${SH_AS:-sh-elf-as}
OD=${SH_OD:-sh-elf-objdump}
LLVM_OD=${LLVM_OBJDUMP:-llvm-project/build/bin/llvm-objdump}
LLVM_RO=${LLVM_READOBJ:-llvm-project/build/bin/llvm-readobj}
tmp=$(mktemp -d)
cat > "$tmp/b.s" <<'EOF'
fwd:    bra there
        mov r0, r0
        bt  there
        bf  back
        bt/s there
        mov r0, r0
        bf/s back
        mov r0, r0
        bsr there
back:   mov r0, r0
there:  rts
        mov r0, r0
EOF
"$MC" --arch=sh -filetype=obj -o "$tmp/llvm.o" "$tmp/b.s" 2>"$tmp/llvm.err" || { echo "FAIL: llvm-mc error"; cat "$tmp/llvm.err"; rm -rf "$tmp"; exit 1; }
"$AS" -o "$tmp/gnu.o" "$tmp/b.s" 2>"$tmp/gnu.err" || { echo "FAIL: sh-elf-as error"; cat "$tmp/gnu.err"; rm -rf "$tmp"; exit 1; }
# Compare the .text section bytes using sh-elf-objdump (canonical for both objects).
# Note: llvm-objdump is not available in this build; sh-elf-objdump reads ELF from either assembler.
llvm_bytes=$("$OD" -s -j .text "$tmp/llvm.o" 2>/dev/null | grep -E '^ ' | awk '{print $2,$3,$4,$5}')
gnu_bytes=$( "$OD" -s -j .text "$tmp/gnu.o"  2>/dev/null | grep -E '^ ' | awk '{print $2,$3,$4,$5}')
if [ "$llvm_bytes" = "$gnu_bytes" ]; then
  echo "BRANCH-RESOLVE: PASS (.text byte-identical to sh-elf-as)"
else
  echo "BRANCH-RESOLVE: FAIL"
  echo "--- llvm ---"
  echo "$llvm_bytes"
  echo "--- gnu ---"
  echo "$gnu_bytes"
  rm -rf "$tmp"
  exit 1
fi

# Relocation type check: bra ext -> type 4 (R_SH_IND12W), bt ext -> type 3 (R_SH_DIR8WPN)
# Use sh-elf-readelf to read reloc types (llvm-readobj shows "Unknown" for SH reloc names).
READELFF=${SH_READELF:-sh-elf-readelf}
printf '\tbra ext\n' | "$MC" --arch=sh -filetype=obj -o "$tmp/rb.o" - 2>/dev/null
printf '\tbt ext\n'  | "$MC" --arch=sh -filetype=obj -o "$tmp/rt.o" - 2>/dev/null

# Info field lower byte = reloc type number (hex in the output)
r_bra=$("$READELFF" -r "$tmp/rb.o" 2>/dev/null | grep -oE '[0-9a-f]{8}  [0-9a-f]{8}' | head -1 | awk '{printf "%d\n", strtonum("0x" substr($2,7,2))}')
r_bt=$( "$READELFF" -r "$tmp/rt.o" 2>/dev/null | grep -oE '[0-9a-f]{8}  [0-9a-f]{8}' | head -1 | awk '{printf "%d\n", strtonum("0x" substr($2,7,2))}')

echo "BRANCH-RELOC: bra=$r_bra bt=$r_bt"

if [ "$r_bra" = "4" ] && [ "$r_bt" = "3" ]; then
  echo "BRANCH-RELOC: PASS (bra=4 R_SH_IND12W, bt=3 R_SH_DIR8WPN)"
else
  echo "BRANCH-RELOC: FAIL (expected bra=4 bt=3)"
  rm -rf "$tmp"
  exit 1
fi

rm -rf "$tmp"
exit 0
