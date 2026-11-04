# Windows portable build

`python3 scripts/build_windows.py --offline` rebuilds from the retained verified downloads.
Without `--offline`, missing upstream artifacts are fetched with TLS verification enabled.
The Python runtime is the official Python Software Foundation NuGet 3.13.7 package.
Its SHA-512 was verified against the NuGet catalog's `packageHash`. The Zig 0.13.0
Linux compiler wheel SHA-256 was verified against PyPI metadata. Pins are in the
build script and `BUILD_PROVENANCE.json` in the distribution.

The C launcher is a native PE32+ x64 Windows GUI application. It forwards arguments
to the included Python runtime without requiring a global Python installation.
The launcher uses UTF-16 Windows APIs, embeds `longPathAware`, leaves elevation
disabled, and checks missing runtime/app directories. It does not modify source data.
The distribution is a complete portable folder, not a single-file self-extracting EXE.

Build output: `dist/Bbolprom-Windows-x64-v0.3.zip`.
Static verification: `python3 scripts/verify_windows_bundle.py`.
On Windows: extract the complete ZIP and open `Bbolprom.exe`.
Optional Windows runtime smoke checks: run `test_windows.ps1` from the extracted folder.
This PowerShell script checks file SHA-256, bundled Python startup, Unicode file
paths, HWPX parsing, original text, image MD5/SHA1, SQLite Unicode roundtrip and
the native launcher invoking the app local HTTP health self-test.

The Linux build and static verification do not establish Windows runtime readiness.
No Windows OS or Wine was available in the build environment. Native startup,
browser launch, file dialogs, Windows long-path behavior and end-to-end real PT
processing remain separate validation requirements. The development EXE is unsigned.
Do not include `desktop/cache` or `desktop/tools` in source delivery; these are
build caches, not application inputs. No evaluation baseline should ship in `app`. The explicit read-only gallery catalog
`app/assets/approved_catalog.json` is display data isolated from operational inference.
