document.addEventListener('DOMContentLoaded', () => {
    // --- Profile Display & Edit Logic --- //
    const activeUser = localStorage.getItem('loggedInUser');
    let customStudentName = localStorage.getItem('studentName') || activeUser || 'Student';
    let customStudentPic = localStorage.getItem('studentPic') || null;

    function updateStudentAvatar(picUrl) {
        const sidebarAvatar = document.getElementById('sidebar-avatar');
        const previewAvatar = document.getElementById('profile-modal-preview');
        const content = picUrl 
            ? `<img src="${picUrl}" style="width:100%; height:100%; object-fit:cover; border-radius:50%;">` 
            : `<i class="ph-fill ph-user"></i>`;
        if (sidebarAvatar) sidebarAvatar.innerHTML = content;
        if (previewAvatar) previewAvatar.innerHTML = content;
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
                const reader = new FileReader();
                reader.onload = (evt) => {
                    tempStudentPic = evt.target.result;
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
                if (tempStudentPic) {
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

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', (e) => {
            e.preventDefault();
            localStorage.removeItem('loggedInUser');
            localStorage.removeItem('studentName');
            localStorage.removeItem('studentPic');
            window.location.href = 'auth.html';
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
            const response = await fetch(`http://127.0.0.1:8000/team-invitations?roll_no=${encodeURIComponent(activeUser)}`);
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
                        <span>Invited by ${escapeInviteHtml(invitation.inviter_roll_no)} · Code ${escapeInviteHtml(invitation.team_code)}</span>
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
            const response = await fetch('http://127.0.0.1:8000/team-invitations', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ inviter_roll_no: activeUser, invitee_roll_no: invitee })
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
            const response = await fetch(`http://127.0.0.1:8000/team-invitations/${item.dataset.invitationId}`, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ roll_no: activeUser, action: button.dataset.inviteAction })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || 'Could not respond to invitation.');
            if (result.status === 'accepted') {
                renderTeamUI(result.team_name, result.team_code, result.members, activeUser);
                notificationsModal.classList.remove('active');
            }
            await loadTeamInvitations();
        } catch (error) {
            alert(error.message);
            item.querySelectorAll('button').forEach(actionButton => { actionButton.disabled = false; });
        }
    });

    async function fetchStudentTeam(rollNo) {
        try {
            const response = await fetch(`http://127.0.0.1:8000/get-student-team?roll_no=${encodeURIComponent(rollNo)}`);
            const data = await response.json();
            if (response.ok && data.has_team) {
                renderTeamUI(data.team_name, data.team_code, data.members, rollNo);
            }
        } catch (error) {
            console.error('Error fetching student team details:', error);
        }
    }

    function renderTeamUI(teamName, teamCode, members, rollNo) {
        // Show roster card with team name
        const rosterCard = document.getElementById('team-roster-card');
        const rosterName = document.getElementById('roster-team-name');
        const rosterMembers = document.getElementById('roster-members');
        const rosterCode = document.getElementById('roster-team-code');
        
        if (rosterName && teamName) rosterName.textContent = 'TEAM: ' + teamName.toUpperCase();
        if (rosterCode && teamCode) rosterCode.textContent = teamCode;

        // Render all current members dynamically
        if (rosterMembers && members) {
            rosterMembers.innerHTML = ''; 
            members.forEach((member, index) => {
                const isLeader = (index === 0) ? '<span class="leader-badge"><i class="ph-fill ph-crown"></i></span>' : '';
                const labelText = (member === rollNo) ? "You (" + member + ")" : member;
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
            // Check file type / validation here if needed
            currentFile = files[0];
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
        uploadStatusText.textContent = 'Upload Complete';
        uploadStatusText.style.color = 'var(--status-verified)';
        progressBar.style.background = 'var(--status-verified)';

        // Enable buttons
        btnSubmit.disabled = false;
        btnCheck.disabled = false;
    }

    // --- Remove File Logic --- //
    removeFileBtn.addEventListener('click', () => {
        currentFile = null;
        fileInput.value = '';
        dropZone.style.display = 'block';
        uploadProgressArea.style.display = 'none';
        evalPanel.style.display = 'none';

        btnSubmit.disabled = true;
        btnCheck.disabled = true;
        progressBar.style.background = 'linear-gradient(90deg, var(--primary), var(--secondary))';
        uploadStatusText.style.color = 'var(--text-muted)';
    });


    // --- Anti-Gravity Checking Simulation --- //
    btnCheck.addEventListener('click', async () => {
        if (!currentFile) return;

        // Ui State Updates
        btnCheck.disabled = true;
        btnCheck.innerHTML = '<i class="ph-fill ph-spinner-gap ph-spin"></i> Checking...';
        btnSubmit.disabled = true;

        chipPending.style.display = 'none';
        chipChecking.style.display = 'inline-flex';

        const title = document.getElementById("project-title").value.trim();
        const desc = document.getElementById("project-desc") ? document.getElementById("project-desc").value.trim() : "";

        const formData = new FormData();
        formData.append("title", title);
        formData.append("description", desc);
        formData.append("file", currentFile);

        try {
            const response = await fetch("http://127.0.0.1:8000/check-plagiarism", {
                method: "POST",
                body: formData
            });
            const data = await response.json();
            
            if (response.ok) {
                finishChecking(data);
            } else {
                alert(data.detail || "Error checking plagiarism");
                resetEvalState();
                btnCheck.innerHTML = '<i class="ph-fill ph-shield-check"></i> Check Plagiarism';
                btnSubmit.disabled = true;
            }
        } catch (err) {
            console.error(err);
            alert("Failed to connect to the server.");
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

        // ENFORCE 30% THRESHOLD FOR SUBMISSION
        if (data.plagiarism_percent <= 30) {
            btnSubmit.disabled = false;
        } else {
            btnSubmit.disabled = true;
            // Introduce a tiny delay so the UI finishes updating the score visually first
            setTimeout(() => {
                alert(`Plagiarism score of ${data.plagiarism_percent}% exceeds the 30% maximum limit. You are blocked from submitting this project.`);
            }, 100);
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
                const rollNo = localStorage.getItem('loggedInUser');

                const response = await fetch('http://127.0.0.1:8000/create-team', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        team_name: teamName,
                        description: description,
                        max_members: parseInt(maxMembers),
                        roll_no: rollNo
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
                    renderTeamUI(data.team_name, data.team_code, data.members, rollNo);
                } else {
                    alert(data.detail || 'Failed to create team');
                }
            } catch (error) {
                console.error('Create Team error:', error);
                alert('Connection error. Is the server running?');
            }
        });
    }

    // Join Team form submission
    const joinTeamFormEl = document.getElementById('join-team-form');
    if (joinTeamFormEl) {
        joinTeamFormEl.addEventListener('submit', async (e) => {
            e.preventDefault();
            const teamCode = document.getElementById('team-code').value;
            const uiRoll = document.getElementById('join-roll') ? document.getElementById('join-roll').value : "";
            const rollNo = localStorage.getItem('loggedInUser') || uiRoll;

            try {
                const response = await fetch('http://127.0.0.1:8000/join-team', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        team_code: teamCode,
                        roll_no: rollNo
                    })
                });

                const data = await response.json();

                if (response.ok) {
                    alert('Successfully joined the team!');
                    joinTeamForm.style.display = 'none';
                    if (btnShowJoinTeam) btnShowJoinTeam.style.display = 'inline-flex';
                    joinTeamFormEl.reset();

                    // Render Team UI using helper
                    renderTeamUI(data.team_name, data.team_code, data.members, rollNo);
                } else {
                    alert(data.detail || data.error || 'Failed to join team');
                }
            } catch (error) {
                console.error('Join Team error:', error);
                alert('Connection error. Is the server running?');
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
            const activeUser = localStorage.getItem('loggedInUser');
            if (!activeUser) {
                alert('Session expired. Please log in again.');
                window.location.href = 'auth.html';
                return;
            }
            if (!confirm('Are you sure you want to leave this team?')) return;

            try {
                const res = await fetch('http://127.0.0.1:8000/leave-team', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ roll_no: activeUser })
                });
                const data = await res.json();

                if (res.ok) {
                    alert('You have left the team.');
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
                    alert(data.detail || 'Failed to leave the team.');
                }
            } catch (err) {
                console.error(err);
                alert('Connection error. Is the server running?');
            }
        });
    }
});
const input = document.getElementById("find-chat-input");
const sendBtn = document.getElementById("find-send-btn");
const chatBox = document.getElementById("find-chat-box");

sendBtn.addEventListener("click", sendMessage);
input.addEventListener("keypress", (e) => {
    if (e.key === "Enter") sendMessage();
});

async function sendMessage() {
    const message = input.value.trim();
    if (!message) return;

    // Disable Send Button
    const originalBtnHtml = sendBtn.innerHTML;
    sendBtn.innerHTML = '<i class="ph ph-spinner-gap ph-spin"></i>';
    sendBtn.disabled = true;

    // 🧑 User message
    const userWrapper = document.createElement('div');
    userWrapper.className = 'message-wrapper user-wrapper';
    userWrapper.innerHTML = '<div class="message-avatar"><i class="ph-fill ph-user"></i></div>';
    const userMessage = document.createElement('div');
    userMessage.className = 'premium-glass-bubble';
    userMessage.textContent = message;
    userWrapper.appendChild(userMessage);
    chatBox.appendChild(userWrapper);
    input.value = "";
    chatBox.scrollTop = chatBox.scrollHeight;

    // 🤖 Create empty AI message container
    const aiWrapper = document.createElement("div");
    aiWrapper.className = "message-wrapper ai-wrapper";
    
    // Add avatar and glass bubble
    aiWrapper.innerHTML = `
        <div class="message-avatar"><i class="ph-fill ph-terminal-window"></i></div>
    `;
    
    const aiMessage = document.createElement("div");
    aiMessage.className = "ai-message premium-glass-bubble streaming-cursor";
    aiWrapper.appendChild(aiMessage);
    chatBox.appendChild(aiWrapper);
    chatBox.scrollTop = chatBox.scrollHeight;

    let pendingText = "";
    const wordDelayMs = 65;

    async function revealCompleteWords() {
        let match;
        while ((match = pendingText.match(/^\s*\S+\s+/))) {
            aiMessage.textContent += match[0];
            pendingText = pendingText.slice(match[0].length);
            chatBox.scrollTop = chatBox.scrollHeight;
            await new Promise(resolve => setTimeout(resolve, wordDelayMs));
        }
    }

    try {
        const res = await fetch(`http://127.0.0.1:8000/chat-stream?prompt=${encodeURIComponent(message)}`);

        // If backend fails
        if (!res.ok) {
            const errText = await res.text().catch(() => "");
            throw new Error(errText || "Server error");
        }

        if (!res.body) throw new Error("Streaming is unavailable in this browser");
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            pendingText += decoder.decode(value, { stream: true });
            await revealCompleteWords();
        }
        pendingText += decoder.decode();
        await revealCompleteWords();
        aiMessage.textContent += pendingText;
        pendingText = "";
        chatBox.scrollTop = chatBox.scrollHeight;
        if (!aiMessage.textContent.trim()) {
            throw new Error("The AI service returned an empty response");
        }

    } catch (err) {
        const errorText = "Error connecting to the AI service. Please make sure the backend is running and GROQ_API_KEY is configured.";
        aiMessage.textContent += pendingText;
        aiMessage.textContent += aiMessage.textContent ? `\n\n${errorText}` : errorText;
        console.error(err);
    } finally {
        aiMessage.classList.remove("streaming-cursor");
        sendBtn.innerHTML = originalBtnHtml;
        sendBtn.disabled = false;
        input.focus();
    }
}
async function submitProject() {
    const titleEl = document.getElementById("project-title");
    const descEl = document.getElementById("project-desc");

    const rollNo = localStorage.getItem("loggedInUser"); // saved during login

    if (!rollNo) {
        alert("Session expired. Please log in again.");
        window.location.href = "auth.html";
        return;
    }

    if (!titleEl.value.trim()) {
        alert("Please fill in the Project Title.");
        return;
    }

    const data = {
        roll_no: rollNo,
        project_name: titleEl.value.trim(),
        project_abstract: descEl ? descEl.value.trim() : ""
    };

    const btnSubmit = document.getElementById("btn-submit");
    btnSubmit.disabled = true;
    btnSubmit.innerHTML = '<i class="ph ph-spinner-gap"></i> Submitting...';

    try {
        const res = await fetch("http://127.0.0.1:8000/submit-project", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Server error");
        }

        const result = await res.json();
        alert(result.message);
        btnSubmit.innerHTML = '<i class="ph ph-check"></i> Submitted';
        btnSubmit.style.background = "var(--status-verified)";
    } catch (err) {
        alert("Submission failed: " + err.message);
        btnSubmit.disabled = false;
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
