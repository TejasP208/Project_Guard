document.addEventListener('DOMContentLoaded', async () => {
    if (window.projectGuardSessionReady && !await window.projectGuardSessionReady) return;
    const view = document.getElementById('view-axiom');
    if (!view || window.projectGuardProfile?.role !== view.dataset.role) return;

    const stream = view.querySelector('.axiom-dashboard-messages');
    const form = view.querySelector('.axiom-dashboard-form');
    const input = form.querySelector('textarea');
    const send = form.querySelector('button');
    const error = view.querySelector('.axiom-dashboard-error');
    let pending = null;

    function append(role, text) {
        const message = document.createElement('article');
        message.className = `axiom-dashboard-message ${role}`;
        const avatar = document.createElement('span');
        avatar.className = 'axiom-message-avatar';
        avatar.setAttribute('aria-hidden', 'true');
        const icon = document.createElement('i');
        icon.className = role === 'assistant' ? 'ph-fill ph-sparkle' : 'ph-fill ph-user';
        avatar.append(icon);
        const content = document.createElement('div');
        content.className = 'axiom-message-content';
        const author = document.createElement('span');
        author.className = 'axiom-message-author';
        author.textContent = role === 'assistant' ? 'Axiom' : 'You';
        const body = document.createElement('div');
        body.className = 'axiom-message-body';
        body.textContent = text;
        content.append(author, body);
        message.append(avatar, content);
        stream.append(message);
        stream.scrollTop = stream.scrollHeight;
        return body;
    }

    function showWelcome() {
        const student = view.dataset.role === 'student';
        const welcome = document.createElement('section');
        welcome.className = 'axiom-welcome';
        const icon = document.createElement('span');
        icon.className = 'axiom-welcome-icon';
        icon.innerHTML = '<i class="ph-fill ph-sparkle" aria-hidden="true"></i>';
        const title = document.createElement('h3');
        title.textContent = student ? 'What can we work on today?' : 'What would you like to review?';
        const subtitle = document.createElement('p');
        subtitle.textContent = student
            ? 'Ask Axiom about your project, or start with one of these ideas.'
            : 'Explore feedback and review ideas here. For uploaded documents, open a project from Project List.';
        const suggestions = document.createElement('div');
        suggestions.className = 'axiom-suggestions';
        const prompts = student
            ? ['Help me improve my project idea', 'What should our team do next?', 'How can I make my work more original?']
            : ['Suggest questions for a project review', 'How can I give useful project feedback?', 'Help me plan the next milestone'];
        for (const prompt of prompts) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'axiom-suggestion';
            button.textContent = prompt;
            button.dataset.prompt = prompt;
            suggestions.append(button);
        }
        welcome.append(icon, title, subtitle, suggestions);
        stream.append(welcome);
    }

    async function loadHistory() {
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/axiom/history?scope=dashboard`);
            const saved = await response.json().catch(() => []);
            if (!response.ok) throw new Error(saved.detail || 'Could not load the conversation.');
            stream.replaceChildren();
            if (saved.length) saved.forEach(turn => append(turn.role, turn.content));
            else showWelcome();
        } catch (failure) {
            error.textContent = failure.message || 'Could not load the conversation.';
            showWelcome();
        }
    }

    async function newChat() {
        if (pending) pending.abort();
        pending = null;
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/axiom/history?scope=dashboard`, { method: 'DELETE' });
            if (!response.ok) throw new Error('Could not clear the conversation.');
        } catch (failure) {
            error.textContent = failure.message;
            return;
        }
        stream.replaceChildren();
        error.textContent = '';
        input.value = '';
        input.style.height = '';
        input.disabled = false;
        send.disabled = false;
        showWelcome();
        if (!view.classList.contains('hidden')) input.focus();
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const question = input.value.trim();
        if (!question || pending) return;
        stream.querySelector('.axiom-welcome')?.remove();
        input.value = '';
        input.style.height = '';
        error.textContent = '';
        append('user', question);
        const reply = append('assistant', '');
        reply.classList.add('is-thinking');
        const controller = new AbortController();
        pending = controller;
        input.disabled = true;
        send.disabled = true;
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/axiom/dashboard-chat`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question }), signal: controller.signal
            });
            if (!response.ok) {
                const detail = await response.json().catch(() => ({}));
                throw new Error(typeof detail.detail === 'string' ? detail.detail : 'Axiom could not answer.');
            }
            if (!response.body) throw new Error('Streaming is unavailable in this browser.');
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;
                reply.classList.remove('is-thinking');
                reply.textContent += decoder.decode(value, { stream: true });
                stream.scrollTop = stream.scrollHeight;
            }
            reply.textContent += decoder.decode();
            reply.classList.remove('is-thinking');
            if (!reply.textContent.trim()) throw new Error('Axiom returned an empty answer.');
        } catch (failure) {
            if (failure.name !== 'AbortError') {
                reply.closest('.axiom-dashboard-message').remove();
                input.value = question;
                error.textContent = failure.message || 'Could not reach Axiom. Try again.';
            }
        } finally {
            if (pending === controller) {
                pending = null;
                input.disabled = false;
                send.disabled = false;
                if (!view.classList.contains('hidden')) input.focus();
            }
        }
    });
    view.querySelector('.axiom-dashboard-clear').addEventListener('click', newChat);
    stream.addEventListener('click', event => {
        const suggestion = event.target.closest('.axiom-suggestion');
        if (!suggestion || pending) return;
        input.value = suggestion.dataset.prompt;
        form.requestSubmit();
    });
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    });
    document.getElementById('nav-axiom')?.addEventListener('click', () => {
        requestAnimationFrame(() => input.focus());
    });
    await loadHistory();
});
