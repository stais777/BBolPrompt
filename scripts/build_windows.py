"""Cross-build portable Windows x64 app on Linux; downloads verified upstream artifacts.

Usage: python3 scripts/build_windows.py [--offline]
The output includes its own Python; users do not install Python.
This is a cross-build, NOT evidence of execution on Windows.
"""
from __future__ import annotations
import argparse, base64, hashlib, json, os, pathlib, re, shutil, subprocess, urllib.request, zipfile
ROOT = pathlib.Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'desktop'
CACHE = DESKTOP / 'cache'
PYTHON_URL = 'https://api.nuget.org/v3-flatcontainer/python/3.13.7/python.3.13.7.nupkg'
PYTHON_SHA512 = '1X7TBUVp/0x51bgfu1zKMthvYHiHt5mYaSkKSxH61fXfdgYb257Idd5rKsh0GAZ/3DOcdDH084hesuGmPJaE2g=='
PYTHON_CATALOG = 'https://api.nuget.org/v3/catalog0/data/2025.08.14.16.10.47/python.3.13.7.json'
ZIG_URL = 'https://files.pythonhosted.org/packages/0c/b7/ecfdce6368cc3664d301f7f52db4fe1004aa7da7a12c4a9bf1de534ff6ab/ziglang-0.13.0-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl'
ZIG_SHA256 = '3ce0c9f16547e5d61b32e0d226926e9a2552ef4b91fccf7ab5ea1a623a77824b'

def artifact(name, url, expected, algorithm, offline):
    path = CACHE / name
    if not path.exists():
        if offline: raise FileNotFoundError(f'Cached artifact missing: {name}')
        with urllib.request.urlopen(url, timeout=90) as response, path.open('wb') as target:
            shutil.copyfileobj(response, target)
    digest = hashlib.new(algorithm, path.read_bytes()).digest()
    actual = base64.b64encode(digest).decode() if algorithm == 'sha512' else digest.hex()
    if actual != expected: raise ValueError(f'Upstream checksum mismatch: {name}')
    return path

def safe_extract(z, folder, prefix=''):
    for info in z.infolist():
        if not info.filename.startswith(prefix) or info.is_dir(): continue
        relative = info.filename[len(prefix):]
        destination = folder / relative
        if not destination.resolve().is_relative_to(folder.resolve()): raise ValueError('ZIP path escape')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info) as source, destination.open('wb') as target: shutil.copyfileobj(source,target)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--offline',action='store_true');parser.add_argument('--version',default='0.3.7-portable');args=parser.parse_args()
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*(?:-[a-z]+)?',args.version):raise ValueError('Invalid artifact version')
    CACHE.mkdir(parents=True,exist_ok=True)
    python=artifact('python.3.13.7.nupkg',PYTHON_URL,PYTHON_SHA512,'sha512',args.offline)
    zigwheel=artifact('ziglang.whl',ZIG_URL,ZIG_SHA256,'sha256',args.offline)
    tools=DESKTOP/'tools'
    with zipfile.ZipFile(zigwheel) as z:safe_extract(z,tools)
    zig=tools/'ziglang/zig';zig.chmod(0o755)
    environment=os.environ.copy();environment['ZIG_GLOBAL_CACHE_DIR']=str(CACHE/'zig-global');environment['ZIG_LOCAL_CACHE_DIR']=str(CACHE/'zig-local')
    launcher=DESKTOP/'Bbolprom.exe'
    command=[str(zig),'cc','-target','x86_64-windows-gnu','-O2','-municode','-Wl,--subsystem,windows',str(DESKTOP/'launcher.c'),str(DESKTOP/'launcher.rc'),'-o',str(launcher)]
    subprocess.run(command,check=True,env=environment,cwd=DESKTOP)
    package=ROOT/'dist/Windows/Bbolprom'
    if package.exists(): shutil.rmtree(package)
    package.mkdir(parents=True)
    shutil.copy2(launcher,package/'Bbolprom.exe')
    with zipfile.ZipFile(python) as z:safe_extract(z,package/'runtime','tools/')
    shutil.copytree(ROOT/'bbolprom_engine', package/'app/bbolprom_engine',ignore=shutil.ignore_patterns('__pycache__','*.pyc','compare.py'))
    # Approved fixed baseline and opt-in API reference catalogue.
    # Evaluation baselines, API keys, local databases, caches, tests and handoff files
    # are excluded from the executable distribution.
    catalog=ROOT/'assets/approved_catalog.json'
    if catalog.exists():
        (package/'app/assets').mkdir(parents=True,exist_ok=True)
        shutil.copy2(catalog,package/'app/assets/approved_catalog.json')
    readme=DESKTOP/'WINDOWS_README.txt'
    if readme.exists(): shutil.copy2(readme,package/'사용방법.txt')
    shutil.copy2(DESKTOP/'windows_smoke.py',package/'windows_smoke.py')
    smoke=ROOT/'scripts/test_windows.ps1'
    if smoke.exists(): shutil.copy2(smoke,package/'test_windows.ps1')
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    source_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    provenance={'version':args.version,'application_source_commit':source_commit,'application_source_clean_at_build':not source_dirty,'cross_built':True,'native_windows_executed':False,'actual_PT_tested':False,'live_API_tested':False,'UI_handoff_applied':True,'target':'Windows 10/11 x64','python':{'version':'3.13.7','source':PYTHON_URL,'upstream_catalog':PYTHON_CATALOG,'sha512_base64':PYTHON_SHA512,'publisher':'Python Software Foundation'},'compiler':{'version':'Zig 0.13.0','source':ZIG_URL,'sha256':ZIG_SHA256},'command':command,'notes':'Unsigned development build. Windows execution is a separate validation requirement.'}
    (package/'BUILD_PROVENANCE.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    hashes={str(p.relative_to(package)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file()}
    (package/'SHA256.json').write_text(json.dumps(hashes,indent=2,ensure_ascii=False),encoding='utf-8')
    destination=ROOT/f'dist/Bbolprom-Windows-x64-v{args.version}.zip'
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(package.parent))
    print(destination)
    print('Archive SHA256:',hashlib.sha256(destination.read_bytes()).hexdigest())
    print('Cross-build complete; native Windows execution NOT performed.')
if __name__=='__main__':main()
