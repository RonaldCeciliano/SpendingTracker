const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8');

function setup() {
    function element(tag) {
        return {
            tag, handlers: {}, children: [], disabled: true, focused: false,
            addEventListener(name, handler) { this.handlers[name] = handler; },
            focus() { this.focused = true; },
            replaceChildren(...children) { this.children = children; },
            contains(child) { return this.children.includes(child); },
            setAttribute(name, value) { this[name] = value; }
        };
    }
    const close = element('button');
    const content = element('div');
    const title = element('h2');
    const body = {style: {overflow: 'auto'}};
    const dialog = Object.assign(element('dialog'), {
        open: false,
        showModal() { this.open = true; },
        close() { this.open = false; this.handlers.close(); },
        querySelector(selector) {
            return {'.expense-receipt-close': close, '.expense-receipt-content': content}[selector];
        }
    });
    const buttons = ['image', 'pdf'].map((type, index) => Object.assign(element('button'), {
        dataset: {receiptType: type, receiptUrl: `/expenses/${index + 1}/receipt`,
            receiptLabel: `Receipt from <Shop ${index + 1}>`}
    }));
    vm.runInNewContext(source, {
        URL, AbortController,
        document: {
            currentScript: {src: "http://localhost/static/js/main.js"},
            body,
            getElementById(id) {
                return {'expense-receipt-dialog': dialog, 'expense-receipt-title': title}[id];
            },
            querySelectorAll(selector) {
                assert.equal(selector, '.expense-receipt-open');
                return buttons;
            },
            createElement: element
        }
    });
    return {close, content, title, body, dialog, buttons};
}

test('image receipt opens in the dialog with a label and Close focus', () => {
    const ui = setup();
    assert.equal(ui.buttons[0].disabled, false);
    ui.buttons[0].handlers.click();
    assert.equal(ui.dialog.open, true);
    const image = ui.content.children[0];
    assert.equal(image.tag, 'img');
    assert.equal(image.src, '/expenses/1/receipt');
    assert.equal(image.alt, ui.buttons[0].dataset.receiptLabel);
    assert.equal(ui.title.textContent, image.alt);
    assert.equal(ui.close.focused, true);
    assert.equal(ui.body.style.overflow, 'hidden');
    ui.close.handlers.click();
    assert.equal(ui.dialog.open, false);
    assert.equal(ui.content.children.length, 0);
    assert.equal(ui.body.style.overflow, 'auto');
    assert.equal(ui.buttons[0].focused, true);
});

test('PDF starts an in-page render and native close restores the latest trigger', () => {
    const ui = setup();
    ui.buttons[0].handlers.click();
    ui.close.handlers.click();
    ui.buttons[0].focused = false;
    ui.buttons[1].handlers.click();
    const pdf = ui.content.children[0];
    assert.equal(pdf.tag, 'div');
    assert.equal(pdf.textContent, 'Loading receipt…');
    // Native Escape dismissal invokes dialog close, just like this simulation.
    ui.dialog.close();
    assert.equal(ui.buttons[1].focused, true);
    assert.equal(ui.buttons[0].focused, false);
    assert.equal(ui.content.children.length, 0);
    assert.equal(ui.body.style.overflow, 'auto');
});

test('opening again while active does not change the receipt or focus return target', () => {
    const ui = setup();
    ui.buttons[0].handlers.click();
    ui.buttons[1].handlers.click();
    assert.equal(ui.content.children[0].tag, 'img');
    ui.close.handlers.click();
    assert.equal(ui.buttons[0].focused, true);
    assert.equal(ui.buttons[1].focused, false);
});

test('missing image shows a useful message and stale errors cannot replace a new preview', () => {
    const ui = setup();
    ui.buttons[0].handlers.click();
    const image = ui.content.children[0];
    image.handlers.error();
    assert.match(ui.content.children[0].textContent, /could not be displayed/);
    assert.equal(ui.content.children[0].role, 'status');
    ui.close.handlers.click();
    ui.buttons[1].handlers.click();
    image.handlers.error();
    assert.equal(ui.content.children[0].tag, 'div');
});
