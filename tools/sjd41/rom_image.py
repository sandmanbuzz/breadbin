#!/usr/bin/env python3
"""Build a private 32 KiB 1541C/1541-II-style ROM from a user's JD 6.01 ROM.

The proprietary base ROM is supplied by the user and never stored here.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROM16=0x4000
BANK_SIZE=0x4000
BASE_SHA256='2de4d06b4aa2a1b1129cc641a01cbac7e631de362dbd6fe2129eec7336afad53'
def sha256(data): return hashlib.sha256(data).hexdigest()
def vectors(image):
 b=image[-ROM16:]
 return {'nmi':b[0x3ffa]|b[0x3ffb]<<8,'reset':b[0x3ffc]|b[0x3ffd]<<8,'irq':b[0x3ffe]|b[0x3fff]<<8}
def inspect(path):
 raw=path.read_bytes(); print(f'file: {path}\nbytes: {len(raw)}\nsha256: {sha256(raw)}')
 if len(raw) not in (ROM16,2*ROM16): print('error: expected 16384 or 32768 bytes',file=sys.stderr); return 2
 print('mapping: '+('16 KiB JD bank at $C000-$FFFF' if len(raw)==ROM16 else '32 KiB image; upper bank at $C000-$FFFF'))
 print('vectors: '+' '.join(f'{k.upper()}=${v:04X}' for k,v in vectors(raw).items()))
 if len(raw)==ROM16: print('known supplied JD 6.01 hash: '+('yes' if sha256(raw)==BASE_SHA256 else 'no'))
 return 0
def build(base_path,extension_path,manifest_path,output_path):
 base=base_path.read_bytes(); ext=extension_path.read_bytes(); m=json.loads(manifest_path.read_text(encoding='utf-8'))
 if m.get('format')!='breadbin-drive-rom-v1': raise ValueError('unsupported manifest format')
 if len(base)!=ROM16: raise ValueError(f'base must be 16384 bytes, got {len(base)}')
 if len(ext)!=BANK_SIZE: raise ValueError(f'extension must be 16384 bytes, got {len(ext)}')
 actual=sha256(base); expected=m.get('base_sha256')
 if not expected or actual.lower()!=expected.lower(): raise ValueError(f'base SHA-256 mismatch: expected {expected!r}, got {actual}')
 patched=bytearray(base); occupied=set(); patches=m.get('patches',[])
 if not isinstance(patches,list): raise ValueError('patches must be an array')
 for i,p in enumerate(patches):
  try: addr=int(p['address'],0) if isinstance(p['address'],str) else int(p['address']); old=bytes.fromhex(p['expect']); new=bytes.fromhex(p['replace'])
  except (KeyError,TypeError,ValueError) as e: raise ValueError(f'invalid patch #{i}: {e}')
  if not 0xC000<=addr<=0xFFFF: raise ValueError(f'patch #{i}: address outside $C000-$FFFF')
  off=addr-0xC000
  if not old or len(old)!=len(new) or off+len(old)>ROM16: raise ValueError(f'patch #{i}: invalid length or bank crossing')
  if any(x in occupied for x in range(off,off+len(old))): raise ValueError(f'patch #{i}: overlaps prior patch')
  occupied.update(range(off,off+len(old)))
  if bytes(patched[off:off+len(old)])!=old: raise ValueError(f'patch #{i} at ${addr:04X}: expected {old.hex()}, found {bytes(patched[off:off+len(old)]).hex()}')
  patched[off:off+len(new)]=new
 result=ext+bytes(patched); output_path.write_bytes(result)
 print(f'wrote {output_path} ({len(result)} bytes), SHA-256 {sha256(result)}')
 print(f'layout: extension $8000-$BFFF; JD-derived bank $C000-$FFFF; {len(patches)} patch records')
 return 0
def main():
 p=argparse.ArgumentParser(description=__doc__); s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('inspect'); a.add_argument('rom',type=Path)
 b=s.add_parser('build'); b.add_argument('--base',required=True,type=Path); b.add_argument('--extension',required=True,type=Path); b.add_argument('--manifest',required=True,type=Path); b.add_argument('--output',required=True,type=Path)
 x=p.parse_args()
 try: return inspect(x.rom) if x.cmd=='inspect' else build(x.base,x.extension,x.manifest,x.output)
 except (OSError,ValueError,json.JSONDecodeError) as e: print(f'error: {e}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
