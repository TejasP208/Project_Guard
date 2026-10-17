// A newly issued Clerk token can briefly precede the API server's clock.
// Retry only that specific rejection; each request obtains a fresh token.
window.projectGuardAuthFetch = async (url, init = {}) => {
    const delays = [1000, 2000, 4000];
    for (let attempt = 0; ; attempt += 1) {
        const response = await window.projectGuardApiFetch(url, init);
        if (response.status !== 401) return response;
        const detail = (await response.clone().json().catch(() => ({}))).detail;
        if (detail !== 'TOKEN_NOT_ACTIVE_YET' || attempt === delays.length) return response;
        await new Promise(resolve => setTimeout(resolve, delays[attempt]));
    }
};
