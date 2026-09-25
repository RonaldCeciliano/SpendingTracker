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
