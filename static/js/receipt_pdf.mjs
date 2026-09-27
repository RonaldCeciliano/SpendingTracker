// Render only page pixels: no viewer, annotation layer, forms, or PDF scripting.
export async function renderReceiptPdf({url, container, label, signal}, loadLibrary = () =>
    import('../vendor/pdfjs/build/pdf.min.mjs')) {
    const pdfjs = await loadLibrary();
    if (signal.aborted) return;
    const assets = new URL('../vendor/pdfjs/', import.meta.url);
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('build/pdf.worker.min.mjs', assets).href;
    const task = pdfjs.getDocument({
        url,
        cMapUrl: new URL('cmaps/', assets).href,
        cMapPacked: true,
        standardFontDataUrl: new URL('standard_fonts/', assets).href,
        wasmUrl: new URL('wasm/', assets).href,
        isEvalSupported: false
    });
    let destroyed = false;
    const destroy = () => {
        if (destroyed) return;
        destroyed = true;
        // Closing during fetch/render can reject outstanding PDF.js operations.
        Promise.resolve(task.destroy()).catch(() => {});
    };
    signal.addEventListener('abort', destroy, {once: true});
    try {
        const pdf = await task.promise;
        if (signal.aborted) return;
        container.replaceChildren();
        for (let number = 1; number <= pdf.numPages; number++) {
            const page = await pdf.getPage(number);
            if (signal.aborted) return;
            const original = page.getViewport({scale: 1});
            const width = Math.max(1, container.clientWidth || 800);
            // Bound canvas allocations even for unusual page dimensions.
            const scale = Math.min(width * Math.min(globalThis.devicePixelRatio || 1, 2) / original.width,
                4096 / Math.max(original.width, original.height),
                Math.sqrt(4000000 / (original.width * original.height)));
            const viewport = page.getViewport({scale});
            const canvas = container.ownerDocument.createElement('canvas');
            canvas.className = 'expense-receipt-pdf-page';
            canvas.width = Math.ceil(viewport.width);
            canvas.height = Math.ceil(viewport.height);
            canvas.setAttribute('role', 'img');
            canvas.setAttribute('aria-label', `${label}, page ${number} of ${pdf.numPages}`);
            container.appendChild(canvas);
            await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
            if (signal.aborted) return;
            page.cleanup();
        }
    } finally {
        signal.removeEventListener('abort', destroy);
        destroy();
    }
}
