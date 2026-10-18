(() => {
    let notice;
    let noticeText;
    let dialog;
    let confirmMessage;
    let confirmTitle;
    let confirmButton;
    let pendingConfirmation = null;

    function initialize() {
        if (notice || !document.body) return;

        notice = document.createElement('div');
        notice.className = 'app-feedback';
        notice.hidden = true;
        notice.setAttribute('aria-atomic', 'true');
        noticeText = document.createElement('span');
        notice.append(noticeText);
        const dismiss = document.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'app-feedback-dismiss';
        dismiss.setAttribute('aria-label', 'Dismiss message');
        dismiss.textContent = '×';
        dismiss.addEventListener('click', () => { notice.hidden = true; });
        notice.append(dismiss);
        document.body.append(notice);

        dialog = document.createElement('dialog');
        dialog.className = 'app-confirm-dialog';
        confirmTitle = document.createElement('h2');
        confirmTitle.id = 'app-confirm-title';
        confirmMessage = document.createElement('p');
        confirmMessage.id = 'app-confirm-message';
        const actions = document.createElement('div');
        actions.className = 'app-confirm-actions';
        const cancelButton = document.createElement('button');
        cancelButton.type = 'button';
        cancelButton.className = 'app-confirm-cancel';
        cancelButton.textContent = 'Cancel';
        cancelButton.addEventListener('click', () => dialog.close('cancel'));
        confirmButton = document.createElement('button');
        confirmButton.type = 'button';
        confirmButton.className = 'app-confirm-accept';
        confirmButton.addEventListener('click', () => dialog.close('confirm'));
        actions.append(cancelButton, confirmButton);
        dialog.setAttribute('aria-labelledby', confirmTitle.id);
        dialog.setAttribute('aria-describedby', confirmMessage.id);
        dialog.append(confirmTitle, confirmMessage, actions);
        dialog.addEventListener('close', () => {
            if (pendingConfirmation) {
                pendingConfirmation(dialog.returnValue === 'confirm');
                pendingConfirmation = null;
            }
        });
        document.body.append(dialog);
    }

    function notify(message, level = 'info') {
        initialize();
        if (!notice) return;
        const isError = level === 'error';
        notice.className = `app-feedback app-feedback--${isError ? 'error' : 'success'}`;
        notice.setAttribute('role', isError ? 'alert' : 'status');
        notice.setAttribute('aria-live', isError ? 'assertive' : 'polite');
        notice.hidden = false;
        noticeText.textContent = String(message ?? '');
    }

    function confirm(message, options = {}) {
        initialize();
        if (!dialog || dialog.open || pendingConfirmation) return Promise.resolve(false);
        confirmTitle.textContent = options.title || 'Confirm action';
        confirmMessage.textContent = String(message ?? '');
        confirmButton.textContent = options.confirmLabel || 'Continue';
        return new Promise(resolve => {
            pendingConfirmation = resolve;
            dialog.showModal();
            dialog.querySelector('.app-confirm-cancel').focus();
        });
    }

    window.projectGuardFeedback = { notify, confirm };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
