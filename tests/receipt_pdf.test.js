const assert = require('node:assert/strict');
const test = require('node:test');

async function setup({fail = false, pending = false} = {}) {
    const {renderReceiptPdf} = await import('../static/js/receipt_pdf.mjs');
    const state = {renders: [], destroyed: 0, cleaned: 0};
    let resolve;
    const task = {
        promise: pending ? new Promise(done => { resolve = done; }) :
            fail ? Promise.reject(new Error('Invalid PDF')) : Promise.resolve({
                numPages: 3,
                async getPage(number) {
                    return {
                        getViewport({scale}) { return {width: 600 * scale, height: 900 * scale}; },
                        render(options) { state.renders.push({number, options}); return {promise: Promise.resolve()}; },
                        cleanup() { state.cleaned++; }
                    };
                }
            }),
        destroy() { state.destroyed++; return Promise.resolve(); }
    };
    const library = {
        GlobalWorkerOptions: {},
        getDocument(options) { state.options = options; return task; }
    };
    const container = {
        clientWidth: 350, children: [],
        replaceChildren() { this.children = []; },
        appendChild(child) { this.children.push(child); },
        ownerDocument: {createElement(tag) {
            return {tag, setAttribute(key, value) { this[key] = value; }, getContext() { return {}; }};
        }}
    };
    const controller = new AbortController();
    const run = () => renderReceiptPdf({url: '/expenses/7/receipt', container,
        label: 'Receipt from Shop', signal: controller.signal}, async () => library);
    return {state, container, controller, run, resolve};
}

test('PDF pages render in vertical order as labeled canvases without viewer controls', async () => {
    const ui = await setup();
    await ui.run();
    assert.deepEqual(ui.state.renders.map(item => item.number), [1, 2, 3]);
    assert.equal(ui.state.options.url, '/expenses/7/receipt');
    assert.equal(ui.state.options.isEvalSupported, false);
    assert.equal(ui.state.cleaned, 3);
    assert.equal(ui.state.destroyed, 1);
    ui.container.children.forEach((canvas, index) => {
        assert.equal(canvas.tag, 'canvas');
        assert.equal(canvas.role, 'img');
        assert.equal(canvas['aria-label'], `Receipt from Shop, page ${index + 1} of 3`);
        assert.equal(canvas.width, 350);
        assert.equal(canvas.height, 525);
    });
});

test('invalid PDF rejects to modal error handler and releases worker', async () => {
    const ui = await setup({fail: true});
    await assert.rejects(ui.run(), /Invalid PDF/);
    assert.equal(ui.state.destroyed, 1);
    assert.equal(ui.container.children.length, 0);
});

test('closing during load destroys the task and prevents stale page insertion', async () => {
    const ui = await setup({pending: true});
    const rendering = ui.run();
    await Promise.resolve();
    ui.controller.abort();
    ui.resolve({numPages: 1});
    await rendering;
    assert.equal(ui.state.destroyed, 1);
    assert.equal(ui.container.children.length, 0);
});

test('closing before library load prevents PDF fetch', async () => {
    const ui = await setup();
    ui.controller.abort();
    await ui.run();
    assert.equal(ui.state.options, undefined);
});
