"""Create source+tests archive without runtime/cache/user-data or other releases."""
import argparse
from pathlib import Path
import re
import zipfile

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--version',default='0.3.1-diagnostic')
args=parser.parse_args()
if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:-[a-z]+)?',args.version):raise ValueError('Invalid version')
out=root/'dist'/f'Bbolprom-Source-v{args.version}.zip'
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(root)
        if rel.parts[0] in ('dist','downloads','.git') or '__pycache__' in rel.parts:continue
        if rel.parts[:2] in (('desktop','cache'),('desktop','tools')):continue
        if p.suffix in ('.pyc','.exe','.pdb','.o','.obj','.sqlite3') or p.name=='.env':continue
        z.write(p,Path('Bbolprom-source')/rel)
with zipfile.ZipFile(out) as z:
    assert z.testzip() is None
    assert 'Bbolprom-source/bbolprom_engine/app.py' in z.namelist()
print(out)
