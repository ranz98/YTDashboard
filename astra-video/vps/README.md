# Windows VPS package

See [WINDOWS-SETUP.md](WINDOWS-SETUP.md) for installation and first-run steps.

The package includes the queue runner, authenticated local Chrome bridge,
Manifest V3 extension, download adapter, existing caption editor integration,
and YouTube Studio upload adapter. Browser uploads require live account validation.

Use `python ../deploy/build_vps.py` to build the credential-free ZIP.
The ZIP preserves the editor scripts and font folders needed by the adapters.
