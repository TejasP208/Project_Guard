document.addEventListener('DOMContentLoaded', async () => {
    if (window.projectGuardSessionReady && !await window.projectGuardSessionReady) return;
    // --- Profile Display & Edit Logic --- //
    const activeUser = window.projectGuardProfile?.identifier;
    let customStudentName = localStorage.getItem('studentName') || activeUser || 'Student';
    const isSafeAvatarDataUrl = value => typeof value === 'string'
        && value.length <= 1_500_000
        && /^data:image\/(?:png|jpeg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$/.test(value);
    const storedStudentPic = localStorage.getItem('studentPic');
    let customStudentPic = isSafeAvatarDataUrl(storedStudentPic) ? storedStudentPic : null;

    function updateStudentAvatar(picUrl) {
        const sidebarAvatar = document.getElementById('sidebar-avatar');
        const previewAvatar = document.getElementById('profile-modal-preview');
        const safePic = isSafeAvatarDataUrl(picUrl) ? picUrl : null;
        for (const avatar of [sidebarAvatar, previewAvatar]) {
            if (!avatar) continue;
            avatar.replaceChildren();
            if (safePic) {
                const image = document.createElement('img');
                image.src = safePic;
                image.alt = '';
                image.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:50%';
                avatar.append(image);
            } else {
                const icon = document.createElement('i');
                icon.className = 'ph-fill ph-user';
                avatar.append(icon);
            }
        }
    }

    const studentNameEl = document.getElementById('student-display-name');
    if (studentNameEl) studentNameEl.textContent = customStudentName;
    updateStudentAvatar(customStudentPic);

    if (activeUser) {
        const subTitle = document.querySelector('.page-subtitle');
        if (subTitle && subTitle.textContent.includes('Unknown')) {
            subTitle.textContent = `Welcome back, ${customStudentName}. Here's your project status.`;
        }
        fetchStudentTeam(activeUser);
        loadTeamInvitations();
        window.setInterval(loadTeamInvitations, 15000);
    }

    // Edit Profile Modal Logic
    let tempStudentPic = customStudentPic;
    const profileModal = document.getElementById('edit-profile-modal');
    const profileTrigger = document.getElementById('user-profile-trigger');
    const closeBtn = document.getElementById('profile-modal-close-btn');
    const cancelBtn = document.getElementById('btn-cancel-profile');
    const picInput = document.getElementById('profile-pic-input');
    const removePicBtn = document.getElementById('btn-remove-photo');
    const profileForm = document.getElementById('edit-profile-form');
    const nameInput = document.getElementById('edit-display-name');

    function openProfileModal() {
        tempStudentPic = localStorage.getItem('studentPic') || null;
        if (nameInput) nameInput.value = localStorage.getItem('studentName') || activeUser || 'Student';
        updateStudentAvatar(tempStudentPic);
        if (profileModal) profileModal.classList.add('active');
    }

    function closeProfileModal() {
        if (profileModal) profileModal.classList.remove('active');
    }

    if (profileTrigger) profileTrigger.addEventListener('click', openProfileModal);
    if (closeBtn) closeBtn.addEventListener('click', closeProfileModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeProfileModal);

    if (picInput) {
        picInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(file.type) || file.size > 1024 * 1024) {
                    picInput.value = '';
                    window.projectGuardFeedback.notify('Choose a PNG, JPEG, WebP, or GIF image up to 1 MB.', 'error');
                    return;
                }
                const reader = new FileReader();
                reader.onload = (evt) => {
                    tempStudentPic = isSafeAvatarDataUrl(evt.target.result) ? evt.target.result : null;
                    updateStudentAvatar(tempStudentPic);
                };
                reader.readAsDataURL(file);
            }
        });
    }

    if (removePicBtn) {
        removePicBtn.addEventListener('click', () => {
            tempStudentPic = null;
            updateStudentAvatar(null);
            if (picInput) picInput.value = '';
        });
    }

    if (profileForm) {
        profileForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const newName = nameInput.value.trim();
            if (newName) {
                localStorage.setItem('studentName', newName);
                if (isSafeAvatarDataUrl(tempStudentPic)) {
                    localStorage.setItem('studentPic', tempStudentPic);
                } else {
                    localStorage.removeItem('studentPic');
                }
                if (studentNameEl) studentNameEl.textContent = newName;
                updateStudentAvatar(tempStudentPic);
                closeProfileModal();
            }
        });
    }

    const inviteModal = document.getElementById('team-invite-modal');
    const notificationsModal = document.getElementById('team-notifications-modal');
    const inviteFeedback = document.getElementById('team-invite-feedback');
    const inviteForm = document.getElementById('team-invite-form');
    const escapeInviteHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);

    function closeInviteModal() {
        inviteModal.classList.remove('active');
        inviteFeedback.textContent = '';
        inviteFeedback.style.color = '';
        inviteForm.reset();
    }

    async function loadTeamInvitations() {
        if (!activeUser) return;
        const list = document.getElementById('team-invitations-list');
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/team-invitations`);
            const invitations = await response.json();
            if (!response.ok) throw new Error(invitations.detail || 'Could not load invitations.');
            document.querySelectorAll('.notification-badge').forEach(badge => {
                badge.textContent = invitations.length;
                badge.hidden = invitations.length === 0;
            });
            if (!list) return;
            if (!invitations.length) {
                list.innerHTML = '<div class="team-invitation-empty"><i class="ph ph-bell-slash" style="font-size:2rem;"></i><p>No pending team invitations.</p></div>';
                return;
            }
            list.innerHTML = invitations.map(invitation => `
                <div class="team-invitation-item" data-invitation-id="${invitation.id}">
                    <div class="team-invitation-icon"><i class="ph ph-users-three"></i></div>
                    <div class="team-invitation-copy">
                        <strong>${escapeInviteHtml(invitation.team_name)}</strong>
                        <span>Invited by ${escapeInviteHtml(invitation.inviter_roll_no)}. Accepting moves you from your current team, if any. Your old team's project stays there.</span>
                    </div>
                    <div class="team-invitation-actions">
                        <button class="btn btn-secondary btn-sm" type="button" data-invite-action="decline">Decline</button>
                        <button class="btn btn-primary btn-sm" type="button" data-invite-action="accept">Accept</button>
                    </div>
                </div>`).join('');
        } catch (error) {
            if (list) list.innerHTML = `<div class="team-invitation-empty" style="color:var(--status-danger);">${escapeInviteHtml(error.message)}</div>`;
        }
    }

    document.querySelectorAll('.notification-btn').forEach(button => {
        button.addEventListener('click', () => {
            notificationsModal.classList.add('active');
            loadTeamInvitations();
        });
    });
    document.getElementById('team-notifications-close').addEventListener('click', () => notificationsModal.classList.remove('active'));
    document.getElementById('team-invite-close').addEventListener('click', closeInviteModal);
    document.getElementById('team-invite-cancel').addEventListener('click', closeInviteModal);
    inviteModal.addEventListener('click', event => { if (event.target === inviteModal) closeInviteModal(); });
    notificationsModal.addEventListener('click', event => { if (event.target === notificationsModal) notificationsModal.classList.remove('active'); });

    document.getElementById('roster-members').addEventListener('click', event => {
        if (!event.target.closest('[data-invite-slot]')) return;
        inviteModal.classList.add('active');
        setTimeout(() => document.getElementById('team-invite-roll').focus(), 100);
    });

    inviteForm.addEventListener('submit', async event => {
        event.preventDefault();
        const submit = document.getElementById('team-invite-submit');
        const invitee = document.getElementById('team-invite-roll').value.trim();
        submit.disabled = true;
        inviteFeedback.textContent = '';
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/team-invitations`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ invitee_roll_no: invitee })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Could not send invitation.');
            inviteFeedback.style.color = 'var(--status-verified)';
            inviteFeedback.textContent = result.message;
            document.getElementById('team-invite-roll').value = '';
        } catch (error) {
            inviteFeedback.style.color = '';
            inviteFeedback.textContent = error.message;
        } finally {
            submit.disabled = false;
        }
    });

    document.getElementById('team-invitations-list').addEventListener('click', async event => {
        const button = event.target.closest('[data-invite-action]');
        if (!button) return;
        const item = button.closest('[data-invitation-id]');
        item.querySelectorAll('button').forEach(actionButton => { actionButton.disabled = true; });
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/team-invitations/${item.dataset.invitationId}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: button.dataset.inviteAction })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Could not respond to invitation.');
            if (result.status === 'accepted') {
                await fetchStudentTeam(activeUser);
                if (window.loadStudentProgress) await window.loadStudentProgress();
                notificationsModal.classList.remove('active');
            }
            await loadTeamInvitations();
        } catch (error) {
            window.projectGuardFeedback.notify(error.message, 'error');
            item.querySelectorAll('button').forEach(actionButton => { actionButton.disabled = false; });
        }
    });

    async function fetchStudentTeam(rollNo) {
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/get-student-team`);
            const data = await response.json();
            if (response.ok && data.has_team) {
                renderTeamUI(data.team_name, data.team_code, data.members, rollNo, data.submission_status, data);
            }
        } catch (error) {
            console.error('Error fetching student team details:', error);
        }
    }

    function renderTeamUI(teamName, teamCode, members, rollNo, submissionStatus = null, details = {}) {
        // Show roster card with team name
        const rosterCard = document.getElementById('team-roster-card');
        const rosterName = document.getElementById('roster-team-name');
        const rosterMembers = document.getElementById('roster-members');
        const rosterCode = document.getElementById('roster-team-code');
        
        if (rosterName) rosterName.textContent = `TEAM: ${(teamName || 'Unnamed team').toUpperCase()}`;
        if (rosterCode) rosterCode.textContent = teamCode || 'Not available';
        const copyRosterCode = document.getElementById('btn-copy-roster-code');
        if (copyRosterCode) copyRosterCode.hidden = !teamCode;
        document.getElementById('roster-group-number').textContent = details.group_no ? `Group ${details.group_no}` : '—';
        document.getElementById('roster-year-department').textContent = `${details.year || '—'} · ${(details.department || 'aiml').toUpperCase()}`;
        document.getElementById('roster-mentor-name').textContent = details.mentor_name || 'Not assigned';
        document.getElementById('roster-project-name').textContent = details.project_name || 'Not yet selected';
        document.getElementById('roster-project-abstract').textContent = details.project_abstract || 'No project abstract submitted yet.';

        // Render all current members dynamically
        if (rosterMembers && members) {
            const escapeTeamHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({
                '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
            })[character]);
            rosterMembers.innerHTML = ''; 
            members.forEach((member, index) => {
                const isLeader = (index === 0) ? '<span class="leader-badge"><i class="ph-fill ph-crown"></i></span>' : '';
                const detail = details.member_details?.find(item => item.roll_no?.toLowerCase() === member?.toLowerCase());
                const name = detail?.name && detail.name !== member ? `${detail.name} (${member})` : member;
                const labelText = (member === rollNo) ? `You · ${escapeTeamHtml(name)}` : escapeTeamHtml(name);
                const leaderClass = (index === 0) ? 'leader' : '';
                
                rosterMembers.innerHTML += `
                    <div class="member-slot filled ${leaderClass}">
                        <div class="member-avatar">
                            <i class="ph-fill ph-user"></i>
                        </div>
                        ${isLeader}
                        <span class="member-label">${labelText}</span>
                    </div>
                `;
            });
            // Append empty slots to maintain visual structure (up to 4)
            for (let i = members.length; i < 4; i++) {
                rosterMembers.innerHTML += `
                    <div class="member-slot empty" data-invite-slot="true" title="Invite a student">
                        <div class="member-avatar empty-avatar"><i class="ph ph-plus"></i></div>
                        <span class="member-label">Invite</span>
                    </div>
                `;
            }
        }

        if (rosterCard) rosterCard.classList.remove('hidden');
        const reviewStatus = document.getElementById('project-review-status');
        if (reviewStatus) {
            const messages = {
                rejected: 'Your project submission was rejected. Update the title or abstract below and resubmit for mentor review.',
                pending: 'Submitted · Awaiting mentor acceptance',
                accepted: 'Your project has been accepted by a mentor.'
            };
            reviewStatus.hidden = !messages[submissionStatus];
            reviewStatus.textContent = messages[submissionStatus] || '';
            if (submissionStatus) reviewStatus.dataset.status = submissionStatus;
        }

        // Hide join/create cards since user now has a team
        const joinCard = document.getElementById('join-team-card');
        if (joinCard) joinCard.style.display = 'none';
        const createCard = document.getElementById('create-team-card');
        if (createCard) createCard.style.display = 'none';
    }

    // Elements
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadProgressArea = document.getElementById('upload-progress-area');
    const fileNameDisplay = document.getElementById('file-name-display');
    const removeFileBtn = document.getElementById('remove-file');
    const progressBar = document.getElementById('upload-progress-bar');
    const uploadPercentage = document.getElementById('upload-percentage');
    const uploadStatusText = document.getElementById('upload-status-text');
    const uploadError = document.getElementById('upload-error');

    // Buttons
    const btnSubmit = document.getElementById('btn-submit');
    const btnCheck = document.getElementById('btn-check');

    // Evaluation
    const evalPanel = document.getElementById('evaluation-panel');
    const chipPending = document.getElementById('chip-pending');
    const chipChecking = document.getElementById('chip-checking');
    const chipVerified = document.getElementById('chip-verified');
    const scoreContainer = document.getElementById('score-container');
    const scoreValue = document.getElementById('score-value');
    const teamCreationResult = document.getElementById('team-creation-result');
    const displayTeamCode = document.getElementById('display-team-code');
    const btnCopyCode = document.getElementById('btn-copy-code');
    const btnDismissResult = document.getElementById('btn-dismiss-result');

    // File state
    let currentFile = null;
    const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;
    const SUPPORTED_DOCUMENT_EXTENSIONS = new Set(['pdf', 'docx', 'txt']);

    // --- Drag and Drop Logic --- //

    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Highlight drop zone
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.add('dragover'), false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('dragover'), false);
    });

    // Handle dropped files
    dropZone.addEventListener('drop', (e) => {
        let dt = e.dataTransfer;
        let files = dt.files;
        handleFiles(files);
    });

    // Click to upload
    dropZone.addEventListener('click', () => {
        if (!currentFile) {
            fileInput.click();
        }
    });

    fileInput.addEventListener('change', function () {
        handleFiles(this.files);
    });

    function handleFiles(files) {
        if (files.length > 0) {
            const file = files[0];
            currentFile = null;
            const extension = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : '';
            if (!SUPPORTED_DOCUMENT_EXTENSIONS.has(extension)) {
                showUploadError('Unsupported file type. Choose a PDF, DOCX, or TXT file.');
                fileInput.value = '';
                return;
            }
            if (file.size > MAX_DOCUMENT_BYTES) {
                showUploadError('This file is larger than 20 MB. Choose a smaller PDF, DOCX, or TXT file.');
                fileInput.value = '';
                return;
            }
            uploadStatusText.style.color = 'var(--text-muted)';
            currentFile = file;
            startUploadSimulation(currentFile.name);
        }
    }

    // --- Upload Simulation Logic --- //
    function startUploadSimulation(fileName) {
        // Hide dropzone interior, show progress
        dropZone.style.display = 'none';
        uploadProgressArea.style.display = 'block';
        evalPanel.style.display = 'block'; // Show eval panel as Pending

        fileNameDisplay.textContent = fileName;
        progressBar.style.width = '0%';
        uploadPercentage.textContent = '0%';
        uploadStatusText.textContent = 'Uploading...';
        clearUploadError();

        // Reset eval state
        resetEvalState();

        // Disable buttons during upload
        btnSubmit.disabled = true;
        btnCheck.disabled = true;

        let progress = 0;
        const uploadInterval = setInterval(() => {
            progress += Math.random() * 15; // Random interval increase
            if (progress >= 100) {
                progress = 100;
                clearInterval(uploadInterval);
                finishUpload();
            }
            progressBar.style.width = progress + '%';
            uploadPercentage.textContent = Math.round(progress) + '%';
        }, 300);
    }

    function finishUpload() {
        uploadStatusText.textContent = 'Ready to check';
        uploadStatusText.style.color = 'var(--status-verified)';
        progressBar.style.background = 'var(--status-verified)';

        // Enable buttons
        btnSubmit.disabled = false;
        btnCheck.disabled = false;
    }

    function showUploadError(message) {
        if (uploadError) {
            uploadError.textContent = message;
            uploadError.hidden = false;
        } else {
            window.projectGuardFeedback.notify(message, 'error');
        }
    }

    function clearUploadError() {
        if (!uploadError) return;
        uploadError.textContent = '';
        uploadError.hidden = true;
        uploadError.classList.remove('advisory');
    }

    // --- Remove File Logic --- //
    removeFileBtn.addEventListener('click', () => {
        currentFile = null;
        fileInput.value = '';
        clearUploadError();
        dropZone.style.display = 'block';
        uploadProgressArea.style.display = 'none';
        evalPanel.style.display = 'none';

        btnSubmit.disabled = false;
        btnCheck.disabled = false;
        progressBar.style.background = 'linear-gradient(90deg, var(--primary), var(--secondary))';
        uploadStatusText.style.color = 'var(--text-muted)';
    });


    // --- Anti-Gravity Checking Simulation --- //
    btnCheck.addEventListener('click', async () => {
        // Ui State Updates
        btnCheck.disabled = true;
        btnCheck.innerHTML = '<i class="ph-fill ph-spinner-gap ph-spin"></i> Checking...';
        btnSubmit.disabled = true;

        chipPending.style.display = 'none';
        chipChecking.style.display = 'inline-flex';
        evalPanel.style.display = 'block';
        clearUploadError();

        const title = document.getElementById("project-title").value.trim();
        const desc = document.getElementById("project-desc") ? document.getElementById("project-desc").value.trim() : "";

        const formData = new FormData();
        formData.append("title", title);
        formData.append("description", desc);
        if (currentFile) formData.append("file", currentFile);

        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/check-plagiarism`, {
                method: "POST",
                body: formData
            });
            const data = await response.json();
            
            if (response.ok) {
                finishChecking(data);
                if (data.document_text_truncated) {
                    showUploadError('The document is within the upload limits, but only its first 500 extracted characters were checked.');
                }
            } else {
                showUploadError(data.detail || "The document could not be checked. Review the file and try again.");
                uploadStatusText.textContent = 'Needs attention';
                uploadStatusText.style.color = 'var(--status-danger, #b42318)';
                resetEvalState();
                btnCheck.innerHTML = '<i class="ph-fill ph-shield-check"></i> Check Plagiarism';
                btnSubmit.disabled = true;
            }
        } catch (err) {
            console.error(err);
            showUploadError('Could not reach the checking service. Check your connection and try again.');
            uploadStatusText.textContent = 'Needs attention';
            uploadStatusText.style.color = 'var(--status-danger, #b42318)';
            resetEvalState();
            btnCheck.innerHTML = '<i class="ph-fill ph-shield-check"></i> Check Plagiarism';
            btnSubmit.disabled = true;
        }
    });

    function finishChecking(data) {
        btnCheck.innerHTML = '<i class="ph-fill ph-check-circle"></i> Checked';

        chipChecking.style.display = 'none';
        chipVerified.style.display = 'inline-flex';

        // Show Score
        scoreContainer.style.display = 'flex';

        // Update score from API
        const scoreNumber = document.querySelector('.score-number');
        const scoreChip = document.getElementById('score-value').querySelector('.chip.similarity');
        
        scoreNumber.textContent = data.plagiarism_percent + '%';
        scoreChip.textContent = data.risk_level + ' Similarity';

        // Styling based on risk
        scoreNumber.className = 'score-number';
        scoreChip.className = 'chip similarity';
        
        if (data.risk_level === "Low") {
            scoreNumber.classList.add('safe');
            scoreChip.classList.add('safe');
        } else if (data.risk_level === "Medium") {
            scoreNumber.classList.add('warning');
            scoreChip.classList.add('warning');
        } else {
            scoreNumber.classList.add('danger');
            scoreChip.classList.add('danger');
        }

        // Add subtle animation
        scoreContainer.style.animation = 'fadeIn 0.5s ease forwards';

        const threshold = data.submission_block_threshold;
        if (typeof threshold === 'number' && data.plagiarism_percent > threshold) {
            btnSubmit.disabled = true;
            showUploadError(`Similarity score ${data.plagiarism_percent}% exceeds the configured ${threshold}% submission limit. Revise the project before submitting.`);
        } else {
            btnSubmit.disabled = false;
            if (typeof threshold !== 'number') {
                uploadError?.classList.add('advisory');
                showUploadError('This similarity score is advisory. No calibrated submission-block threshold is configured yet.');
            }
        }
    }

    function resetEvalState() {
        chipPending.style.display = 'inline-flex';
        chipChecking.style.display = 'none';
        chipVerified.style.display = 'none';
        scoreContainer.style.display = 'none';

        btnCheck.innerHTML = '<i class="ph-fill ph-shield-check"></i> Check  Plagiarism';
    }

    // Form Submission — handled by submitProject() via onclick on the submit button
    const form = document.getElementById('submission-form');
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        // Actual submission is handled by submitProject()
    });

    // --- Navigation & View Switching --- //
    const navItems = {
        'nav-dashboard': 'view-dashboard',
        'nav-find': 'view-find',
        'nav-submit': 'view-submit',
        'nav-team': 'view-team',
        'nav-group-connect': 'view-group-connect',
        'nav-axiom': 'view-axiom',
        'nav-plagiarism': 'view-plagiarism',
        'nav-settings': 'view-settings'
    };

    function switchView(targetNavId) {
        // Update active nav class
        document.querySelectorAll('.sidebar-nav .nav-item').forEach(nav => {
            nav.classList.remove('active');
        });
        document.getElementById(targetNavId).classList.add('active');

        // Hide all views, show target view
        document.querySelectorAll('.content-view').forEach(view => {
            view.classList.add('hidden');
        });
        document.getElementById(navItems[targetNavId]).classList.remove('hidden');
        if (targetNavId === 'nav-find' || targetNavId === 'nav-dashboard') loadStudentProgress();
        if (targetNavId === 'nav-team') fetchStudentTeam(activeUser);
    }

    // Attach click listeners to nav items
    Object.keys(navItems).forEach(navId => {
        const navEl = document.getElementById(navId);
        if (navEl) {
            navEl.addEventListener('click', (e) => {
                e.preventDefault();
                switchView(navId);
            });
        }
    });

    // Initialize default view based on active nav item
    const activeNav = document.querySelector('.sidebar-nav .nav-item.active');
    if (activeNav) {
        switchView(activeNav.id);
    }

    // Fake Axiom AI setup removed in favor of real streaming endpoint below

    // --- Team Form Toggle Logic --- //
    const btnShowCreateTeam = document.getElementById('btn-show-create-team');
    const btnShowJoinTeam = document.getElementById('btn-show-join-team');
    const createTeamForm = document.getElementById('create-team-form');
    const joinTeamForm = document.getElementById('join-team-form');
    const cancelCreateTeam = document.getElementById('cancel-create-team');
    const cancelJoinTeam = document.getElementById('cancel-join-team');

    if (btnShowCreateTeam) {
        btnShowCreateTeam.addEventListener('click', () => {
            createTeamForm.style.display = 'block';
            btnShowCreateTeam.style.display = 'none';
        });
    }
    if (cancelCreateTeam) {
        cancelCreateTeam.addEventListener('click', () => {
            createTeamForm.style.display = 'none';
            btnShowCreateTeam.style.display = 'inline-flex';
        });
    }
    if (btnShowJoinTeam) {
        btnShowJoinTeam.addEventListener('click', () => {
            joinTeamForm.style.display = 'block';
            btnShowJoinTeam.style.display = 'none';
        });
    }
    if (cancelJoinTeam) {
        cancelJoinTeam.addEventListener('click', () => {
            joinTeamForm.style.display = 'none';
            btnShowJoinTeam.style.display = 'inline-flex';
        });
    }

    // Create Team form submission
    const createTeamFormEl = document.getElementById('create-team-form');
    if (createTeamFormEl) {
        createTeamFormEl.addEventListener('submit', async (e) => {
            e.preventDefault();
            const teamName = document.getElementById('team-name').value;
            const description = document.getElementById('team-desc')?.value || "";
            const maxMembers = document.getElementById('team-max')?.value || 4;

            try {
                const rollNo = window.projectGuardProfile?.identifier;

                const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/create-team`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        team_name: teamName,
                        description: description,
                        max_members: parseInt(maxMembers),
                        github_url: ''
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    createTeamForm.style.display = 'none';
                    btnShowCreateTeam.style.display = 'none';
                    teamCreationResult.classList.remove('hidden');
                    displayTeamCode.textContent = data.team_code;
                    createTeamFormEl.reset();

                    // Render Team UI using helper
                    await fetchStudentTeam(rollNo);
                    if (window.loadStudentProgress) await window.loadStudentProgress();
                } else {
                    window.projectGuardFeedback.notify(data.detail || 'Failed to create team', 'error');
                }
            } catch (error) {
                console.error('Create Team error:', error);
                window.projectGuardFeedback.notify('Could not connect to the service. Check your connection and try again.', 'error');
            }
        });
    }

    // Join Team form submission
    const joinTeamFormEl = document.getElementById('join-team-form');
    if (joinTeamFormEl) {
        joinTeamFormEl.addEventListener('submit', async (e) => {
            e.preventDefault();
            const teamCode = document.getElementById('team-code').value;
            const rollNo = window.projectGuardProfile?.identifier;
            if (!rollNo) return;

            try {
                const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/join-team`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        team_code: teamCode
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    window.projectGuardFeedback.notify('Successfully joined the team.', 'success');
                    joinTeamForm.style.display = 'none';
                    if (btnShowJoinTeam) btnShowJoinTeam.style.display = 'inline-flex';
                    joinTeamFormEl.reset();

                    // Render Team UI using helper
                    await fetchStudentTeam(rollNo);
                    if (window.loadStudentProgress) await window.loadStudentProgress();
                } else {
                    window.projectGuardFeedback.notify(data.detail || data.error || 'Failed to join team', 'error');
                }
            } catch (error) {
                console.error('Join Team error:', error);
                window.projectGuardFeedback.notify('Could not connect to the service. Check your connection and try again.', 'error');
            }
        });
    }

    // Copy roster team code button
    const btnCopyRosterCode = document.getElementById('btn-copy-roster-code');
    if (btnCopyRosterCode) {
        btnCopyRosterCode.addEventListener('click', () => {
            const rosterCode = document.getElementById('roster-team-code');
            const code = rosterCode.textContent;
            navigator.clipboard.writeText(code).then(() => {
                const originalHTML = btnCopyRosterCode.innerHTML;
                btnCopyRosterCode.innerHTML = '<i class="ph ph-check"></i>';
                btnCopyRosterCode.style.color = 'var(--status-verified)';
                
                setTimeout(() => {
                    btnCopyRosterCode.innerHTML = originalHTML;
                    btnCopyRosterCode.style.color = '';
                }, 2000);
            });
        });
    }

    // --- 3-Dots Roster Menu Toggle --- //
    const btnRosterMenu = document.getElementById('btn-roster-menu');
    const rosterDropdown = document.getElementById('roster-dropdown');

    if (btnRosterMenu && rosterDropdown) {
        // Toggle dropdown on click
        btnRosterMenu.addEventListener('click', (e) => {
            e.stopPropagation();
            rosterDropdown.classList.toggle('hidden');
        });

        // Close dropdown when clicking anywhere else
        document.addEventListener('click', () => {
            rosterDropdown.classList.add('hidden');
        });
    }

    // --- Leave Team --- //
    const btnLeaveTeam = document.getElementById('btn-leave-team');
    if (btnLeaveTeam) {
        btnLeaveTeam.addEventListener('mouseenter', () => {
            btnLeaveTeam.style.background = 'rgba(239,68,68,0.08)';
        });
        btnLeaveTeam.addEventListener('mouseleave', () => {
            btnLeaveTeam.style.background = 'transparent';
        });

        btnLeaveTeam.addEventListener('click', async () => {
            const activeUser = window.projectGuardProfile?.identifier;
            if (!activeUser) {
                window.location.href = 'auth.html?notice=session-expired';
                return;
            }
            if (!await window.projectGuardFeedback.confirm('Are you sure you want to leave this team?', {
                title: 'Leave team', confirmLabel: 'Leave team'
            })) return;

            try {
                const res = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/leave-team`, {
                    method: 'POST'
                });
                const data = await res.json();

                if (res.ok) {
                    window.projectGuardFeedback.notify('You have left the team.', 'success');
                    // Hide roster card
                    const rosterCard = document.getElementById('team-roster-card');
                    if (rosterCard) rosterCard.classList.add('hidden');
                    // Show create / join cards again
                    const joinCard = document.getElementById('join-team-card');
                    if (joinCard) joinCard.style.display = '';
                    const createCard = document.getElementById('create-team-card');
                    if (createCard) createCard.style.display = '';
                    // Re-show action buttons
                    const showCreate = document.getElementById('btn-show-create-team');
                    if (showCreate) showCreate.style.display = 'inline-flex';
                    const showJoin = document.getElementById('btn-show-join-team');
                    if (showJoin) showJoin.style.display = 'inline-flex';
                    // Hide success result card if visible
                    const resultCard = document.getElementById('team-creation-result');
                    if (resultCard) resultCard.classList.add('hidden');
                } else {
                    window.projectGuardFeedback.notify(data.detail || 'Failed to leave the team.', 'error');
                }
            } catch (err) {
                console.error(err);
                window.projectGuardFeedback.notify('Could not connect to the service. Check your connection and try again.', 'error');
            }
        });
    }

    function renderRepository(url) {
        const link = document.getElementById('student-project-github');
        const empty = document.getElementById('student-repository-empty');
        if (url) {
            link.href = url;
            link.textContent = url.replace(/^https:\/\/github\.com\//i, '');
            link.hidden = false;
            empty.hidden = true;
        } else {
            link.removeAttribute('href');
            link.textContent = '';
            link.hidden = true;
            empty.hidden = false;
        }
        document.getElementById('student-dashboard-github').value = url || '';
    }

    async function loadStudentProgress() {
        const summary = document.getElementById('student-project-summary');
        const reviewAction = document.getElementById('student-review-action');
        reviewAction.hidden = true;
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/student/project-progress`);
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Could not load project progress.');
            summary.textContent = `${data.project_name || 'No project selected'} · ${data.submission_status.replaceAll('_', ' ')}`;
            renderRepository(data.github_url);
            document.getElementById('student-project-title').textContent = data.project_name || 'Project not yet selected';
            document.getElementById('student-project-team').textContent = data.team_name || '—';
            document.getElementById('student-project-group').textContent = data.group_no ? `Group ${data.group_no}` : '—';
            document.getElementById('student-project-mentor').textContent = data.mentor_name || 'Not assigned';
            document.getElementById('student-project-status').textContent = data.submission_status.replaceAll('_', ' ');
            document.getElementById('student-project-members').textContent = data.members.length
                ? data.members.map(member => member.name === member.roll_no ? member.roll_no : `${member.name} (${member.roll_no})`).join(', ')
                : 'No team members yet';
            document.getElementById('student-project-abstract').textContent = data.project_abstract || 'No abstract submitted yet.';
            const activeReview = data.active_review;
            const milestones = [
                { label: 'Project idea', done: data.submission_status === 'accepted', active: data.submission_status === 'pending' },
                { label: 'Review 1', done: data.review1 === 'completed', active: activeReview?.number === 1 },
                { label: 'Review 2', done: data.review2 === 'completed', active: activeReview?.number === 2 },
                { label: 'Review 3', done: data.review3 === 'completed', active: activeReview?.number === 3 },
                { label: 'Research paper', done: Boolean(data.documents.research_paper), active: false },
                { label: 'Project report', done: Boolean(data.documents.project_report), active: false }
            ];
            const completed = milestones.filter(item => item.done).length;
            document.getElementById('student-progress-percent').textContent = `${Math.round(completed / milestones.length * 100)}%`;
            document.getElementById('student-progress-bar').style.width = `${Math.round(completed / milestones.length * 100)}%`;
            const list = document.getElementById('student-progress-milestones');
            list.replaceChildren();
            for (const {label, done, active} of milestones) {
                const item = document.createElement('li');
                item.className = done ? 'completed' : active ? 'active' : 'pending';
                const icon = document.createElement('i');
                icon.className = done ? 'ph-fill ph-check-circle' : active ? 'ph-fill ph-spinner-gap' : 'ph ph-circle';
                icon.setAttribute('aria-hidden', 'true');
                item.append(icon, document.createTextNode(label));
                list.append(item);
            }
            if (activeReview) {
                reviewAction.hidden = false;
                document.getElementById('student-progress-slot').value = activeReview.slot;
                document.getElementById('student-review-title').textContent = `${activeReview.label} submission`;
                const when = activeReview.date ? `Scheduled ${activeReview.date}${activeReview.time ? ` at ${activeReview.time}` : ''}. ` : '';
                document.getElementById('student-review-description').textContent = `${when}${activeReview.status === 'pending' ? 'Your document is submitted and awaiting completion. You can replace it.' : 'Your mentor has assigned this review. Upload its document here.'}`;
                document.getElementById('student-review-submit').textContent = activeReview.status === 'pending' ? `Replace ${activeReview.label} document` : `Submit ${activeReview.label} document`;
            }
            document.getElementById('student-topic-change-section').hidden = data.submission_status !== 'accepted';
            document.getElementById('student-topic-change-status').textContent = data.topic_change ? `Latest topic change request: ${data.topic_change}` : '';
        } catch (error) { summary.textContent = error.message; document.getElementById('student-topic-change-section').hidden = true; }
    }
    document.getElementById('student-progress-upload-form').addEventListener('submit', async event => {
        event.preventDefault();
        const status = document.getElementById('student-progress-upload-status');
        const slot = document.getElementById('student-progress-slot').value;
        const payload = new FormData();
        payload.append('file', document.getElementById('student-progress-file').files[0]);
        status.textContent = 'Uploading…';
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/student/project-documents/${slot}`, { method: 'POST', body: payload });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Upload failed.');
            status.textContent = `${data.filename} uploaded.`;
            await loadStudentProgress();
        } catch (error) { status.textContent = error.message; }
    });
    document.getElementById('student-dashboard-github-form').addEventListener('submit', async event => {
        event.preventDefault();
        const status = document.getElementById('student-repository-status');
        const button = event.currentTarget.querySelector('button[type="submit"]');
        button.disabled = true;
        status.textContent = 'Saving repository…';
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/my-team/github`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ github_url: document.getElementById('student-dashboard-github').value })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Could not save repository.');
            renderRepository(data.github_url);
            status.textContent = data.github_url ? 'Repository saved.' : 'Repository link removed.';
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
    });
    document.getElementById('student-topic-change-form').addEventListener('submit', async event => {
        event.preventDefault();
        const status = document.getElementById('student-topic-change-status');
        try {
            const response = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/student/topic-change-requests`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ proposed_title: document.getElementById('student-new-title').value,
                    proposed_abstract: document.getElementById('student-new-abstract').value,
                    reason: document.getElementById('student-change-reason').value })
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.detail || 'Could not send request.');
            status.textContent = 'Topic change request sent to your mentor.';
            await loadStudentProgress();
        } catch (error) { status.textContent = error.message; }
    });
    window.loadStudentProgress = loadStudentProgress;
    loadStudentProgress();
    window.addEventListener('focus', () => {
        if (!document.getElementById('view-find').classList.contains('hidden')) loadStudentProgress();
        if (!document.getElementById('view-team').classList.contains('hidden')) fetchStudentTeam(activeUser);
    });
    setInterval(() => {
        if (document.visibilityState === 'visible' && !document.getElementById('view-find').classList.contains('hidden')) loadStudentProgress();
        if (document.visibilityState === 'visible' && !document.getElementById('view-team').classList.contains('hidden')) fetchStudentTeam(activeUser);
    }, 30000);
});
async function submitProject() {
    const titleEl = document.getElementById("project-title");
    const descEl = document.getElementById("project-desc");

    const rollNo = window.projectGuardProfile?.identifier;

    if (!rollNo) {
        window.location.href = "auth.html?notice=session-expired";
        return;
    }

    if (!titleEl.value.trim()) {
        const validationMessage = document.getElementById('upload-error');
        if (validationMessage) {
            validationMessage.textContent = 'Please fill in the Project Title.';
            validationMessage.hidden = false;
        } else {
            window.projectGuardFeedback.notify('Please fill in the Project Title.', 'error');
        }
        titleEl.focus();
        return;
    }

    const data = {
        project_name: titleEl.value.trim(),
        project_abstract: descEl ? descEl.value.trim() : ""
    };

    const btnSubmit = document.getElementById("btn-submit");
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<i class="ph ph-spinner-gap"></i> Checking and submitting...';

    try {
        const payload = new FormData();
        payload.append('project_name', data.project_name);
        payload.append('project_abstract', data.project_abstract);
        const selectedFile = document.getElementById('file-input')?.files?.[0];
        if (selectedFile) payload.append('file', selectedFile);
        const res = await window.projectGuardApiFetch(`${window.projectGuardApiBaseUrl}/submit-project-with-file`, {
            method: "POST", body: payload
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Server error");
        }

        const result = await res.json();
        window.projectGuardFeedback.notify(result.message || 'Project submitted successfully.', 'success');
        const reviewStatus = document.getElementById('project-review-status');
        if (reviewStatus) {
            reviewStatus.hidden = false;
            reviewStatus.textContent = 'Submitted · Awaiting mentor acceptance';
            reviewStatus.dataset.status = 'pending';
        }
        btnSubmit.innerHTML = '<i class="ph ph-check"></i> Submitted';
        btnSubmit.style.background = "var(--status-verified)";
        if (window.loadStudentProgress) await window.loadStudentProgress();
    } catch (err) {
        const errorPanel = document.getElementById('upload-error');
        if (errorPanel) {
            errorPanel.textContent = `Submission failed: ${err.message}`;
            errorPanel.hidden = false;
        }
        btnSubmit.disabled = /^Submission blocked:/.test(err.message);
        btnSubmit.innerHTML = '<i class="ph ph-upload-simple"></i> Submit Your Project';
    }
}
// Copy button
const btnCopyCodeEl = document.getElementById('btn-copy-code');
if (btnCopyCodeEl) {
    btnCopyCodeEl.addEventListener('click', () => {
        const codeEl = document.getElementById('display-team-code');
        const code = codeEl.textContent;
        navigator.clipboard.writeText(code).then(() => {
            const originalHTML = btnCopyCodeEl.innerHTML;
            btnCopyCodeEl.innerHTML = '<i class="ph ph-check"></i>';
            btnCopyCodeEl.style.background = 'var(--status-verified)';
            btnCopyCodeEl.style.color = 'white';
            
            setTimeout(() => {
                btnCopyCodeEl.innerHTML = originalHTML;
                btnCopyCodeEl.style.background = '';
                btnCopyCodeEl.style.color = '';
            }, 2000);
        });
    });
}

// Dismiss button
const btnDismissResultEl = document.getElementById('btn-dismiss-result');
if (btnDismissResultEl) {
    btnDismissResultEl.addEventListener('click', () => {
        const resultCard = document.getElementById('team-creation-result');
        const showCreateBtn = document.getElementById('btn-show-create-team');
        resultCard.classList.add('hidden');
        if (showCreateBtn) showCreateBtn.style.display = 'inline-flex';
    });
}
