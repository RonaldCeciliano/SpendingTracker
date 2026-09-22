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
