(() => {
    const modal = document.getElementById('demo-modal');
    const trigger = document.getElementById('open-demo');
    if (!modal || !trigger) return;

    const videoContainer = modal.querySelector('.demo-modal-video');
    const videoTemplate = document.getElementById('demo-video-template');
    const closeButton = modal.querySelector('.demo-modal-close');
    let previousOverflow;

    trigger.addEventListener('click', () => {
        if (modal.open) return;
        previousOverflow = document.body.style.overflow;
        videoContainer.replaceChildren(videoTemplate.content.cloneNode(true));
        modal.showModal();
        document.body.style.overflow = 'hidden';
    });

    closeButton.addEventListener('click', () => modal.close());

    modal.addEventListener('click', (event) => {
        if (event.target !== modal) return;
        const bounds = modal.getBoundingClientRect();
        if (event.clientX < bounds.left || event.clientX > bounds.right ||
            event.clientY < bounds.top || event.clientY > bounds.bottom) {
            modal.close();
        }
    });

    // Runs for the close button, backdrop click, and native Escape dismissal.
    modal.addEventListener('close', () => {
        videoContainer.replaceChildren();
        document.body.style.overflow = previousOverflow;
        trigger.focus();
    });
})();

(() => {
    const dialog = document.getElementById('expense-delete-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') return;

    const cancel = dialog.querySelector('.expense-delete-cancel');
    const confirm = dialog.querySelector('.expense-delete-confirm');
    const summary = dialog.querySelector('.expense-delete-summary');
    let selectedForm = null;
    let trigger = null;

    document.querySelectorAll('.expense-delete-form').forEach((form) => {
        const button = form.querySelector('button[type="submit"]');
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            if (dialog.open) return;
            selectedForm = form;
            trigger = button;
            summary.textContent = form.dataset.expenseSummary;
            confirm.disabled = false;
            dialog.showModal();
            cancel.focus();
        });
        button.disabled = false;
    });

    cancel.addEventListener('click', () => dialog.close());
    // Closing with Cancel or Escape never submits the selected form.
    dialog.addEventListener('close', () => {
        selectedForm = null;
        if (trigger) trigger.focus();
        trigger = null;
    });
    confirm.addEventListener('click', () => {
        if (!dialog.open || !selectedForm || confirm.disabled) return;
        confirm.disabled = true;
        // Submit the original POST form, including its existing CSRF token.
        // Bypass the submit listener that opened this confirmation dialog.
        HTMLFormElement.prototype.submit.call(selectedForm);
    });
})();

(() => {
    const dialog = document.getElementById('expense-receipt-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') return;

    const close = dialog.querySelector('.expense-receipt-close');
    const content = dialog.querySelector('.expense-receipt-content');
    const title = document.getElementById('expense-receipt-title');
    let trigger = null;
    let previousOverflow;
    let controller = null;
    const rendererUrl = new URL('receipt_pdf.mjs', document.currentScript.src).href;

    function showError(preview) {
        if (!content.contains(preview)) return;
        const error = document.createElement('p');
        error.textContent = 'This receipt could not be displayed. It may be missing, damaged, or password-protected.';
        error.setAttribute('role', 'status');
        content.replaceChildren(error);
    }

    document.querySelectorAll('.expense-receipt-open').forEach((button) => {
        button.addEventListener('click', async () => {
            if (dialog.open) return;
            trigger = button;
            controller = new AbortController();
            const signal = controller.signal;
            const label = button.dataset.receiptLabel;
            const isPdf = button.dataset.receiptType === 'pdf';
            const preview = document.createElement(isPdf ? 'div' : 'img');
            if (isPdf) {
                preview.textContent = 'Loading receipt…';
            } else {
                preview.className = 'expense-receipt-image';
                preview.alt = label;
                preview.addEventListener('error', () => showError(preview));
                preview.src = button.dataset.receiptUrl;
            }
            title.textContent = label;
            content.replaceChildren(preview);
            previousOverflow = document.body.style.overflow;
            dialog.showModal();
            document.body.style.overflow = 'hidden';
            close.focus();
            if (isPdf) {
                try {
                    const {renderReceiptPdf} = await import(rendererUrl);
                    if (!signal.aborted) {
                        await renderReceiptPdf({url: button.dataset.receiptUrl,
                            container: preview, label, signal});
                    }
                } catch {
                    if (!signal.aborted) showError(preview);
                }
            }
        });
        button.disabled = false;
    });

    close.addEventListener('click', () => dialog.close());
    // Native Escape dismissal fires the same close event as the Close button.
    dialog.addEventListener('close', () => {
        if (controller) controller.abort();
        controller = null;
        content.replaceChildren();
        document.body.style.overflow = previousOverflow;
        if (trigger) trigger.focus();
        trigger = null;
    });
})();
