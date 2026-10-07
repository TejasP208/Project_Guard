// Browser-safe Clerk configuration is served by FastAPI. Never put the Clerk
// secret key in this file or any other frontend asset.
window.projectGuardClerkReady = (async () => {
    // Set the production Render URL in deployment-config.js. Local development
    // keeps the existing static-server/API ports and never needs production keys.
    const isLocalFrontend = ['localhost', '127.0.0.1'].includes(window.location.hostname);
    const configuredApiBaseUrl = window.PROJECT_GUARD_API_BASE_URL?.trim();
    const apiBaseUrl = configuredApiBaseUrl || (isLocalFrontend ? 'http://127.0.0.1:8000' : '');
    if (!apiBaseUrl) {
        throw new Error('Set PROJECT_GUARD_API_BASE_URL to the deployed HTTPS API origin in deployment-config.js.');
    }
    const parsedApiBaseUrl = new URL(apiBaseUrl);
    if (!isLocalFrontend && parsedApiBaseUrl.protocol !== 'https:') {
        throw new Error('The deployed application API must use HTTPS.');
    }
    if (parsedApiBaseUrl.username || parsedApiBaseUrl.password || parsedApiBaseUrl.search || parsedApiBaseUrl.hash) {
        throw new Error('PROJECT_GUARD_API_BASE_URL must be an origin URL without credentials, query, or fragment.');
    }
    const normalizedApiBaseUrl = parsedApiBaseUrl.origin;
    window.projectGuardApiBaseUrl = normalizedApiBaseUrl;
    const response = await fetch(`${normalizedApiBaseUrl}/api/config`);
    if (!response.ok) {
        throw new Error("Clerk configuration is unavailable.");
    }
    const { clerk_publishable_key: publishableKey } = await response.json();
    if (!publishableKey) {
        throw new Error("Clerk publishable key is missing.");
    }

    // Clerk encodes its Frontend API domain in the publishable key.
    const encodedDomain = publishableKey.split("_")[2];
    if (!encodedDomain) {
        throw new Error("Clerk publishable key is invalid.");
    }
    const clerkDomain = atob(encodedDomain.replace(/\$$/, "")).replace(/\$$/, "");
    const loadScript = (src, attributes = {}) => new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.crossOrigin = "anonymous";
        Object.entries(attributes).forEach(([key, value]) => script.setAttribute(key, value));
        script.onload = resolve;
        script.onerror = () => reject(new Error("Could not load Clerk JavaScript."));
        document.head.appendChild(script);
    });

    await loadScript(`https://${clerkDomain}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`, {
        "data-clerk-publishable-key": publishableKey,
    });
    const loadOptions = {};
    if (document.body.dataset.clerkUi === 'true') {
        await loadScript(`https://${clerkDomain}/npm/@clerk/ui@1/dist/ui.browser.js`);
        if (!window.__internal_ClerkUICtor) {
            throw new Error('Clerk sign-in components could not initialize. Refresh and retry.');
        }
        loadOptions.ui = { ClerkUI: window.__internal_ClerkUICtor };
    }
    await window.Clerk.load(loadOptions);

    // Attach the active Clerk session to every frontend request sent through
    // this helper. Local API URLs are rewritten to the configured API origin.
    window.projectGuardApiFetch = async (input, init = {}) => {
        const source = input instanceof Request ? input.url : String(input);
        const target = new URL(source, window.location.href);
        const apiOrigin = normalizedApiBaseUrl;
        const isLocalApi = ['localhost', '127.0.0.1'].includes(target.hostname) && target.port === '8000';
        const isConfiguredApi = target.origin === apiOrigin;
        if (!isLocalApi && !isConfiguredApi) {
            throw new Error('projectGuardApiFetch only supports the configured application API.');
        }
        const url = new URL(`${target.pathname}${target.search}${target.hash}`, apiOrigin);
        const headers = new Headers(input instanceof Request ? input.headers : undefined);
        new Headers(init.headers).forEach((value, key) => headers.set(key, value));
        if (!headers.has('Authorization')) {
            const token = await window.Clerk.session?.getToken();
            if (!token) throw new Error('No active Clerk session token is available. Sign in again and retry.');
            headers.set('Authorization', `Bearer ${token}`);
        }
        return fetch(url, {...init, headers});
    };
    return window.Clerk;
})();
