document.addEventListener('DOMContentLoaded', () => {
    // Navigation Items
    const navDashboard = document.getElementById('nav-dashboard');
    const navProjectList = document.getElementById('nav-project-list');
    const navStudentList = document.getElementById('nav-student-list');
    
    // Content Areas
    const mainTitle = document.getElementById('main-title');
    const mainSubtitle = document.getElementById('main-subtitle');
    const contentContainer = document.getElementById('content-container');

    const navItems = [navDashboard, navProjectList, navStudentList];

    function setActiveNav(activeItem) {
        navItems.forEach(item => {
            if (item) item.classList.remove('active');
        });
        if (activeItem) activeItem.classList.add('active');
    }

    // Dashboard View
    if (navDashboard) {
        navDashboard.addEventListener('click', (e) => {
            e.preventDefault();
            setActiveNav(navDashboard);
            mainTitle.textContent = 'Mentor Dashboard';
            mainSubtitle.textContent = 'Overview of your assigned student groups';
            
            contentContainer.innerHTML = `
                <div class="card glass-card" style="min-height: 400px; display: flex; align-items: center; justify-content: center; flex-direction: column; text-align: center; color: var(--text-muted);">
                    <i class="ph ph-squares-four" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                    <h2>Dashboard Empty</h2>
                    <p>Metrics and updates will appear here.</p>
                </div>
            `;
        });
    }

    // Project Data
    let allProjects = [];

    // Helper to render the Project List UI
    async function renderProjectListUI() {
        mainTitle.textContent = 'Project List';
        mainSubtitle.textContent = 'View submitted projects from groups';
        
        contentContainer.innerHTML = `
            <div class="filter-container">
                <span class="filter-label"><i class="ph ph-funnel"></i> Filter by Year:</span>
                <div class="checkbox-group" id="year-filters">
                    <label class="checkbox-item">
                        <input type="checkbox" value="2nd Year"> 2nd Year
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" value="3rd Year"> 3rd Year
                    </label>
                    <label class="checkbox-item">
                        <input type="checkbox" value="4th Year"> 4th Year
                    </label>
                </div>
            </div>
            <div class="project-grid" id="project-grid-container">
                <div style="color: var(--text-secondary); grid-column: 1 / -1; text-align: center;"><i class="ph ph-spinner-gap ph-spin"></i> Loading projects...</div>
            </div>
        `;

        const filterCheckboxes = document.querySelectorAll('#year-filters input[type="checkbox"]');
        const gridContainer = document.getElementById('project-grid-container');

        // Fetch from database
        try {
            const response = await fetch('http://127.0.0.1:8000/api/projects');
            if (response.ok) {
                allProjects = await response.json();
            } else {
                console.error("Failed to fetch projects:", response.status);
                throw new Error("Failed to fetch");
            }
        } catch (error) {
            console.error("Error fetching projects:", error);
            gridContainer.innerHTML = `
                <div style="color: var(--status-pending); background: rgba(234, 179, 8, 0.1); padding: 1rem; border-radius: 0.5rem; display: flex; align-items: center; gap: 0.5rem; grid-column: 1 / -1;">
                    <i class="ph-fill ph-warning"></i>
                    Failed to load projects. Ensure backend server is running on port 8000.
                </div>
            `;
            return;
        }

        // Function to render projects based on selected filters
        function updateProjectDisplay() {
            // Get selected years
            const selectedYears = Array.from(filterCheckboxes)
                .filter(cb => cb.checked)
                .map(cb => cb.value);
            
            // Filter logic: If nothing selected, show all. Else show matching years.
            let filteredProjects = allProjects;
            if (selectedYears.length > 0) {
                filteredProjects = allProjects.filter(p => p.year && selectedYears.includes(p.year));
            }

            // Render
            if (filteredProjects.length === 0) {
                gridContainer.innerHTML = `
                    <div class="empty-state">
                        <i class="ph ph-folder-dashed"></i>
                        <h3>No Projects Found</h3>
                        <p>No projects match your current filter selection or none submitted yet.</p>
                    </div>
                `;
                return;
            }

            let html = '';
            filteredProjects.forEach(p => {
                // Determine chip style from db or default
                let chipClass = 'pending';
                let chipIcon = 'ph-clock';
                let chipText = 'Pending';
                
                // Assuming status could be checking or verified, using default 'verified' since db may not have it
                if(p.status === 'checking') {
                    chipClass = 'checking';
                    chipIcon = 'ph-spinner-gap';
                    chipText = 'Checking';
                } else if (p.status === 'verified' || !p.status) {
                    chipClass = 'verified';
                    chipIcon = 'ph-check-circle';
                    chipText = 'Verified';
                }

                html += `
                    <div class="project-card">
                        <div class="project-info">
                            <h3 class="project-title" style="text-transform: capitalize;">${p.project_name}</h3>
                            <div class="project-meta">
                                <span><i class="ph ph-users"></i> ${p.team || 'Students'}</span>
                                <span><i class="ph ph-calendar-blank"></i> ${p.year || 'N/A'}</span>
                                <span><i class="ph ph-hash"></i> Group ${p.group_no || '--'}</span>
                            </div>
                        </div>
                        <div class="project-actions">
                            <span class="chip ${chipClass}"><i class="ph ${chipIcon}"></i> ${chipText}</span>
                            <button class="icon-btn glass-btn" title="View Details">
                                <i class="ph ph-caret-right"></i>
                            </button>
                        </div>
                    </div>
                `;
            });
            gridContainer.innerHTML = html;
        }

        // Attach listeners
        filterCheckboxes.forEach(cb => {
            cb.addEventListener('change', updateProjectDisplay);
        });

        // Initial render
        updateProjectDisplay();
    }

    // Project List View
    if (navProjectList) {
        navProjectList.addEventListener('click', (e) => {
            e.preventDefault();
            setActiveNav(navProjectList);
            renderProjectListUI();
        });
    }

    // Student List View
    if (navStudentList) {
        navStudentList.addEventListener('click', (e) => {
            e.preventDefault();
            setActiveNav(navStudentList);
            mainTitle.textContent = 'Student List';
            mainSubtitle.textContent = 'Manage student groups under your guidance';
            
            contentContainer.innerHTML = `
                <div class="card glass-card" style="min-height: 400px; display: flex; align-items: center; justify-content: center; flex-direction: column; text-align: center; color: var(--text-muted);">
                    <i class="ph ph-users" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.5;"></i>
                    <h2>Student List Empty</h2>
                    <p>Student groups under your supervision will be listed here.</p>
                </div>
            `;
        });
    }
});