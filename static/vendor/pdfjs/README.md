# PDF.js receipt renderer

Vendored pdfjs-dist 6.3.289 from https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-6.3.289.tgz.
Apache-2.0; see LICENSE and supporting asset licenses. Only minified renderer/worker,
CMaps, standard fonts, and WASM rendering resources are included; no viewer UI.
Loaded on demand by static/js/receipt_pdf.mjs. No runtime CDN or npm build required.

To update, fetch a reviewed pdfjs-dist release, verify its npm dist.integrity SHA-512,
and replace these same files/directories together (renderer and worker must match).
Exclude quickjs-eval.js and quickjs-eval.wasm: neither bundled rendering module
references them, and ExpenseHQ does not run the PDF scripting sandbox.
Run the application validation suite and manually check multipage, scanned, and
non-Latin PDFs in desktop/mobile browsers. Keep upstream licenses.

Pinned package integrity:
sha512-ZHjSVpDa3D6izMq8/04lvkhkATUmL9px6ChPaXc1k6nU2Mrhlg1/7F0bdUqCwUjw3NsPTfPZsMDUU6ZIcRaeQw==

## Runtime asset audit

- `build/pdf.min.mjs`: display API imported by receipt_pdf.mjs.
- `build/pdf.worker.min.mjs`: matching parser/rendering worker.
- `cmaps/*.bcmap` (168): built-in character maps selected by PDF encoding,
  including inherited maps, fetched through cMapUrl with cMapPacked enabled.
- `standard_fonts/*.pfb` (10) and `*.ttf` (4): standard font substitutes
  selected by the worker when a PDF lacks usable embedded/system fonts.
- `wasm/jbig2.wasm`: JBIG2 and CCITT scanned-image decoding.
- `wasm/openjpeg.wasm`: JPEG 2000 image decoding.
- `wasm/qcms_bg.wasm`: embedded ICC color-profile conversion.
- `wasm/jbig2_nowasm_fallback.js` and `openjpeg_nowasm_fallback.js`:
  worker-loaded decoder fallbacks if WebAssembly initialization fails.
- All LICENSE files are retained for the redistributed code, fonts and maps.

This README is ExpenseHQ's provenance/update record, not upstream package docs.
No viewer, examples, tests, TypeScript definitions, source maps, unminified or
alternate builds are bundled. The two minified build files are runtime code.
Do not trim CMaps or font variants based only on a sample receipt: other valid
PDFs can select different mappings or standard-font variants dynamically.
