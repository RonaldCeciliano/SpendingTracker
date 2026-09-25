const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/js/main.js'), 'utf8');

function setup() {
    function element() {
        return {
            handlers: {}, disabled: true, focused: false,
            addEventListener(name, handler) { this.handlers[name] = handler; },
            focus() { this.focused = true; }
        };
    }
    const cancel = element();
    const confirm = element();
    const summary = {};
    const dialog = Object.assign(element(), {
        open: false,
        showModal() { this.open = true; },
        close() { this.open = false; this.handlers.close(); },
        querySelector(selector) {
            return {'.expense-delete-cancel': cancel, '.expense-delete-confirm': confirm,
                '.expense-delete-summary': summary}[selector];
        }
    });
    const forms = ['First expense', '<b>Second expense</b>'].map((label) => {
        const button = element();
        return Object.assign(element(), {
            button, dataset: {expenseSummary: label}, submissions: 0,
            querySelector() { return button; }
        });
    });
    vm.runInNewContext(source, {
        document: {
            getElementById(id) { return id === 'expense-delete-dialog' ? dialog : null; },
            querySelectorAll() { return forms; }
        },
        HTMLFormElement: {prototype: {submit() { this.submissions++; }}},
        window: {confirm() { assert.fail('Native confirmation must never be used'); }}
    });
    function open(index) {
        let prevented = false;
        forms[index].handlers.submit({preventDefault() { prevented = true; }});
        assert.equal(prevented, true);
        assert.equal(dialog.open, true);
    }
    return {cancel, confirm, summary, dialog, forms, open};
}

test('opening and canceling sends no request and restores focus', () => {
    const ui = setup();
    ui.open(0);
    assert.equal(ui.cancel.focused, true);
    assert.equal(ui.summary.textContent, 'First expense');
    assert.deepEqual(ui.forms.map(form => form.submissions), [0, 0]);
    ui.cancel.handlers.click();
    assert.equal(ui.dialog.open, false);
    assert.equal(ui.forms[0].button.focused, true);
    ui.confirm.handlers.click();
    assert.deepEqual(ui.forms.map(form => form.submissions), [0, 0]);
});

test('confirmation submits only the latest selected original form once', () => {
    const ui = setup();
    ui.open(0);
    ui.cancel.handlers.click();
    ui.open(1);
    assert.equal(ui.summary.textContent, '<b>Second expense</b>');
    ui.confirm.handlers.click();
    ui.confirm.handlers.click();
    assert.deepEqual(ui.forms.map(form => form.submissions), [0, 1]);
});

test('dialog close (including Escape) clears the pending deletion', () => {
    const ui = setup();
    ui.open(1);
    ui.dialog.close();
    ui.confirm.handlers.click();
    assert.deepEqual(ui.forms.map(form => form.submissions), [0, 0]);
    assert.equal(ui.forms[1].button.focused, true);
});

test('native confirm calls are absent', () => {
    assert.doesNotMatch(source, /\bconfirm\s*\(/);
});
