"""Static bundle verification on any OS; NOT a Windows execution test."""
import hashlib,json,pathlib,struct
root=pathlib.Path(__file__).resolve().parents[1]
package=root/'dist/Windows/Bbolprom'
manifest=json.loads((package/'SHA256.json').read_text(encoding='utf-8'))
for name,expected in manifest.items():
    file=package/name
    assert file.resolve().is_relative_to(package.resolve())
    assert hashlib.sha256(file.read_bytes()).hexdigest()==expected,name
exe=(package/'Bbolprom.exe').read_bytes()
assert exe[:2]==b'MZ'
pe=struct.unpack_from('<I',exe,0x3c)[0]
assert exe[pe:pe+4]==b'PE\0\0'
assert struct.unpack_from('<H',exe,pe+4)[0]==0x8664,'Expected AMD64'
assert struct.unpack_from('<H',exe,pe+24)[0]==0x20b,'Expected PE32+'
assert struct.unpack_from('<H',exe,pe+24+68)[0]==2,'Expected Windows GUI subsystem'
assert b'longPathAware' in exe,'Missing embedded long path manifest'
assert '--portable-root'.encode('utf-16-le') in exe,'Missing executable-relative portable data argument'
assert 'startup-error-message.txt'.encode('utf-16-le') in exe,'Missing current-run startup error popup'
assert (package/'runtime/pythonw.exe').is_file()
assert (package/'runtime/python313.dll').is_file()
assert (package/'runtime/DLLs/_sqlite3.pyd').is_file()
assert (package/'runtime/DLLs/_ctypes.pyd').is_file()
assert (package/'runtime/LICENSE.txt').is_file()
assert (package/'app/bbolprom_engine/app.py').is_file()
for path in (package/'app').rglob('*'):
    assert 'reference' not in path.parts
    assert path.name not in {'approved_baseline_309.json','compare.py','comparison.json'}
    if path.suffix=='.py': compile(path.read_bytes(),str(path),'exec')
print(json.dumps({'files_hash_verified':len(manifest),'launcher':'PE32+ AMD64 GUI','long_path_manifest':True,'runtime_upstream_hash':'verified during build','runtime_executed':False,'app_python_sources_compiled_on_host':True,'evaluation_baseline_bundled':False}))
