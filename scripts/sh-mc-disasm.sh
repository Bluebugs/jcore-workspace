#!/usr/bin/env bash
# Disasm round-trip: assemble -> disassemble -> reassemble, assert byte-identical.
# Input (stdin): TSV lines "asm<TAB>hex" (same format as sh-mc-roundtrip.sh).
# The hex field uses space-separated lowercase hex bytes e.g. "33 21 60 10".
# Exits 0 if all pass, 1 if any fail.
set -uo pipefail
LLVM_MC="${LLVM_MC:-llvm-project/build/bin/llvm-mc}"

pass=0; fail=0
while IFS=$'\t' read -r asm hex; do
  [ -z "$asm" ] && continue

  # Step 1: assemble the asm text -> bytes (via llvm-mc)
  enc=$("$LLVM_MC" --arch=sh -show-encoding <<<"$asm" 2>/dev/null \
        | sed -n 's/.*encoding: \[\(.*\)\].*/\1/p' | tr ',' ' ' | sed 's/0x//g')
  if [ -z "$enc" ]; then
    echo "DISASM-RT fail[asm]: '$asm' (no encoding)"; fail=$((fail+1)); continue
  fi

  # Step 2: disassemble the bytes via llvm-mc --disassemble
  # Input format for --disassemble: space-separated 0x.. tokens per line
  hex_tokens=$(echo $enc | sed 's/\([0-9a-fA-F]\{2\}\)/0x\1/g')
  dis=$("$LLVM_MC" --arch=sh --disassemble <<<"$hex_tokens" 2>/dev/null \
        | sed 's/^[[:space:]]*//' | grep -v '^$' | head -1)
  if [ -z "$dis" ]; then
    echo "DISASM-RT fail[dis]: '$asm' [$enc] (disassembler returned nothing)"; fail=$((fail+1)); continue
  fi

  # Step 3: reassemble the disassembled text -> bytes
  reenc=$("$LLVM_MC" --arch=sh -show-encoding <<<"$dis" 2>/dev/null \
          | sed -n 's/.*encoding: \[\(.*\)\].*/\1/p' | tr ',' ' ' | sed 's/0x//g')
  if [ -z "$reenc" ]; then
    echo "DISASM-RT fail[reasm]: '$asm' -> '$dis' (no re-encoding)"; fail=$((fail+1)); continue
  fi

  # Assert byte-identical
  got=$(echo $enc | tr 'A-F' 'a-f')
  regot=$(echo $reenc | tr 'A-F' 'a-f')
  if [ "$got" != "$regot" ]; then
    echo "DISASM-RT fail[mismatch]: '$asm' orig=[$got] reasm=[$regot] (via '$dis')"; fail=$((fail+1))
  else
    pass=$((pass+1))
  fi
done
echo "----"
echo "DISASM-RT pass $pass / fail $fail"
[ "$fail" -eq 0 ]
