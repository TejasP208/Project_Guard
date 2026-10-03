document.addEventListener('DOMContentLoaded', async () => {
    if (window.projectGuardSessionReady && !await window.projectGuardSessionReady) return;
    const view = document.getElementById('view-group-connect');
    if (!view) return;
    const profile = window.projectGuardProfile;
    if (!profile) return;
    const role = profile.role;
    const user = profile.identifier;
    if (role !== view.dataset.role || !user) return;
    const api = `${window.projectGuardApiBaseUrl}/group-connect`;
    const list = document.getElementById('group-selector-list');
    const stream = document.getElementById('group-chat-stream');
    const input = document.getElementById('group-chat-input');
    const error = document.getElementById('group-connect-error');
    const reviews = document.getElementById('group-connect-reviews');
    let groups = [];
    let selectedId = null;
    let loading = false;
    let sending = false;
    let messageSignature = null;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
    const identity = () => ({role, user});
    const query = params => new URLSearchParams({...identity(), ...params});
    const controls = [...view.querySelectorAll('#group-chat-form input, #group-chat-form button, .chat-room-actions button')];

    async function request(path, options) {
        const response = await window.projectGuardApiFetch(`${api}${path}`, options);
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not connect to the group.');
        return result;
    }

    function renderRoom() {
        const group = groups.find(item => item.id === selectedId);
        controls.forEach(control => { control.disabled = !group || sending; });
        document.getElementById('total-groups-badge').textContent = `${groups.length} ${groups.length === 1 ? 'Group' : 'Groups'}`;
        list.innerHTML = groups.length ? groups.map(item => `
            <button type="button" class="group-item ${item.id === selectedId ? 'active' : ''}" data-id="${escape(item.id)}">
                <span class="group-item-title">${escape(item.name)} <i class="ph ph-caret-right"></i></span>
                <span class="group-item-sub">${escape(item.project)}</span>
                <span class="group-item-sub">Mentor: ${escape(item.mentor)}</span>
            </button>`).join('') : '<p class="group-empty-state">No assigned groups yet.</p>';
        document.getElementById('active-group-title').textContent = group ? `${group.name} — ${group.project}` : 'No assigned group';
        document.getElementById('active-group-members').textContent = group ? `Mentor: ${group.mentor} · Members: ${group.members.join(', ')}` : '';
        reviews.innerHTML = group?.reviews.length ? group.reviews.map(review => `
            <div class="group-review"><i class="ph ph-calendar-check"></i>
                <strong>${escape(review.type)}</strong> · ${escape(review.date)} at ${escape(review.time)}
                ${review.notes ? `<span>${escape(review.notes)}</span>` : ''}
            </div>`).join('') : '';
        if (!group) {
            stream.textContent = role === 'student'
                ? 'Your mentor needs to assign your PRN / roll number to a group in their student roster.'
                : 'Assign students to a group in your student roster to start chatting.';
        }
    }

    async function loadMessages() {
        const room = selectedId;
        if (!room) return;
        const messages = await request(`/messages?${query({group_id: room})}`);
        if (room !== selectedId) return;
        const signature = JSON.stringify([room, messages]);
        if (signature === messageSignature) return;
        const nearBottom = stream.scrollHeight - stream.scrollTop - stream.clientHeight < 80;
        const firstRender = messageSignature === null;
        messageSignature = signature;
        stream.innerHTML = messages.length ? messages.map(message => {
            const own = message.role === role && message.user.toLowerCase() === user.trim().toLowerCase();
            const time = new Date(message.created_at).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'});
            return `<div class="chat-bubble ${own ? 'own' : 'other'}">
                <span class="sender-label">${escape(own ? 'You' : message.name)} (${escape(message.role)})</span>
                <div class="group-message-text">${escape(message.text)}</div>
                ${message.meet_link ? `<a class="group-meet-link" href="${escape(message.meet_link)}" target="_blank" rel="noopener noreferrer"><i class="ph ph-video-camera"></i> Join Meet</a>` : ''}
                <span class="chat-time">${escape(time)}</span>
            </div>`;
        }).join('') : '<p class="group-empty-state">No messages yet. Send the first message to your group.</p>';
        if (nearBottom || firstRender) stream.scrollTop = stream.scrollHeight;
    }

    async function refresh() {
        if (loading) return;
        loading = true;
        try {
            groups = await request(`/groups?${query({})}`);
            if (!groups.some(group => group.id === selectedId)) {
                selectedId = groups[0]?.id || null;
                messageSignature = null;
                input.value = '';
            }
            renderRoom();
            await loadMessages();
            error.textContent = '';
        } catch (failure) {
            error.textContent = failure.message.includes('fetch') ? 'Could not reach Group Connect. Check that the backend is running.' : failure.message;
            groups = [];
            selectedId = null;
            messageSignature = null;
            renderRoom();
        } finally {
            loading = false;
        }
    }

    async function send(text = '', meetLink = '') {
        if (!selectedId || sending) return;
        const room = selectedId;
        sending = true;
        error.textContent = '';
        renderRoom();
        try {
            await request('/messages', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({...identity(), group_id: room, text, meet_link: meetLink})
            });
            if (room === selectedId) input.value = '';
            await loadMessages();
            stream.scrollTop = stream.scrollHeight;
        } catch (failure) {
            error.textContent = failure.message;
        } finally {
            sending = false;
            renderRoom();
        }
    }

    list.addEventListener('click', event => {
        const item = event.target.closest('[data-id]');
        if (!item || sending) return;
        selectedId = item.dataset.id;
        messageSignature = null;
        input.value = '';
        error.textContent = '';
        stream.textContent = 'Loading messages...';
        renderRoom();
        loadMessages().catch(failure => { error.textContent = failure.message; });
    });
    document.getElementById('group-chat-form').addEventListener('submit', event => {
        event.preventDefault();
        const text = input.value.trim();
        if (text) send(text);
    });
    document.getElementById('btn-start-instant-meet').addEventListener('click', () => {
        window.open('https://meet.google.com/new', '_blank', 'noopener,noreferrer');
        error.textContent = 'After creating your meeting, use Share Meet Link to send its link to the group.';
    });
    document.getElementById('btn-chat-send-meet-link').addEventListener('click', () => {
        const link = window.prompt('Paste the Google Meet link to share with your group:');
        if (link?.trim()) send('', link.trim());
    });
    const schedule = document.getElementById('btn-schedule-group-meet');
    if (schedule) schedule.addEventListener('click', () => {
        const group = groups.find(item => item.id === selectedId);
        if (group) document.getElementById('review-group').value = group.number;
    });
    document.getElementById('nav-group-connect').addEventListener('click', refresh);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !view.classList.contains('hidden')) refresh();
    });
    window.refreshGroupConnect = refresh;
    window.setInterval(() => {
        if (!document.hidden && !view.classList.contains('hidden')) refresh();
    }, 5000);
    renderRoom();
});
