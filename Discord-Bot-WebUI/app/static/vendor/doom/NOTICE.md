# Vendored DOOM (easter egg)

Powers the Konami-code easter egg in `app/templates/base_flowbite.html`
(`↑↑↓↓←→←→BA`). These files are **lazy-loaded only when the egg fires** — they
add nothing to normal page loads.

## Files

| File | ~Size | What it is | License |
|------|-------|-----------|---------|
| `js-dos.js` | 108 KB | js-dos v6.22.60 loader | GPL-2.0 (DOSBox) |
| `wdosbox.js` | 190 KB | DOSBox WASM glue (eval'd by js-dos after the wasm compiles) | GPL-2.0 |
| `wdosbox.wasm.js` | 1.8 MB | DOSBox compiled to WebAssembly — a raw `.wasm` binary despite the `.js` name | GPL-2.0 |
| `doom.zip` | 2.1 MB | `DOOM.EXE` + `DOOM1.WAD` (shareware Episode 1) | id shareware license |
| `README.TXT`, `HELPME.TXT` | — | Original id Software shareware docs / distribution license | id shareware license |

## Provenance

- **js-dos** v6.22.60 — from the `js-dos` npm package (https://js-dos.com).
  ⚠️ js-dos derives the wasm URL as `wdosboxUrl.replace('.js', '.wasm.js')`, so
  the binary **must** be named `wdosbox.wasm.js` — naming it `wdosbox.wasm`
  makes the fetch 404 and the egg silently falls back to the raycaster.
  js-dos XHRs it as an arraybuffer, `WebAssembly.compile()`s it, then fetches
  and `eval`s `wdosbox.js` with `instantiateWasm` pre-supplied — the glue never
  fetches the binary itself.
- **DOOM** — the *shareware* Episode 1 ("Knee-Deep in the Dead"), DOOM v1.9,
  from the Internet Archive item `DoomsharewareEpisode`. `doom.zip` contains
  only `DOOM.EXE` and `DOOM1.WAD` repackaged for js-dos's `fs.extract()`.

## Licensing / redistribution

The shareware DOOM episode was released by id Software as **freely
redistributable**. See `README.TXT` for id's original distribution terms. This
is the shareware WAD (`DOOM1.WAD`) only — **not** the commercial `DOOM.WAD` /
`DOOM2.WAD`, which are not included and must never be. js-dos / DOSBox are
GPL-2.0. All of the above is safe to commit to a public repository.

## How to refresh

```
# js-dos runtime
curl -sL -o js-dos.js    https://unpkg.com/js-dos@6.22.60/dist/js-dos.js
curl -sL -o wdosbox.js   https://unpkg.com/js-dos@6.22.60/dist/wdosbox.js
# note the .wasm.js name — js-dos requires it (see Provenance above)
curl -sL -o wdosbox.wasm.js https://unpkg.com/js-dos@6.22.60/dist/wdosbox.wasm

# game payload: DOOM.EXE + DOOM1.WAD from the shareware zip, zipped for js-dos
# (source: https://archive.org/details/DoomsharewareEpisode)
```
