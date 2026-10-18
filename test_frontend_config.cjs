// Configuration/session transport checks with a fake Clerk client; no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Frontend/clerk-config.js', 'utf8');

function browser(hostname, configured = '', inHead = false) {
    const calls = [];
    let domReady;
    let clerkLoads = 0;
    const window = {
        location: {hostname, href: `http${hostname === 'localhost' ? '' : 's'}://${hostname}/index.html`},
        PROJECT_GUARD_API_BASE_URL: configured,
        Clerk: {load: async () => { clerkLoads += 1; }, session: {getToken: async () => 'fixture-session'}},
    };
    const document = {
        body: inHead ? null : {dataset: {}},
        addEventListener(event, callback) { if (event === 'DOMContentLoaded') domReady = callback; },
        createElement: () => ({setAttribute() {}}),
        head: {appendChild: script => queueMicrotask(() => script.onload())},
    };
    const context = vm.createContext({window, URL, Headers, Request, atob,
        document,
        fetch: async (url, options) => {
            calls.push({url: String(url), options});
            return {ok: true, json: async () => ({clerk_publishable_key: 'pk_test_' + Buffer.from('fixture.clerk.accounts.dev$').toString('base64')})};
        },
    });
    vm.runInContext(source, context);
    return {window, calls, get clerkLoads() { return clerkLoads; },
        finishDocument() { document.body = {dataset: {}}; domReady(); }};
}

(async () => {
    const local = browser('localhost');
    await local.window.projectGuardClerkReady;
    await local.window.projectGuardApiFetch('http://127.0.0.1:8000/api/me');
    assert.equal(local.calls[1].options.headers.get('Authorization'), 'Bearer fixture-session');
    await assert.rejects(local.window.projectGuardApiFetch('https://foreign.example/api/me'), /configured application API/);
    local.window.Clerk.session = null;
    await assert.rejects(local.window.projectGuardApiFetch('http://127.0.0.1:8000/api/me'), /No active Clerk session/);
    await assert.rejects(browser('portal.example').window.projectGuardClerkReady, /Set PROJECT_GUARD_API_BASE_URL/);
    await assert.rejects(browser('portal.example', 'http://api.example').window.projectGuardClerkReady, /must use HTTPS/);
    const production = browser('portal.example', 'https://api.example');
    await production.window.projectGuardClerkReady;
    await production.window.projectGuardApiFetch('http://127.0.0.1:8000/api/projects');
    assert.equal(production.calls[1].url, 'https://api.example/api/projects');
    const head = browser('localhost', '', true);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(head.clerkLoads, 0, 'Wait for the dashboard body before reading Clerk UI configuration');
    head.finishDocument();
    await head.window.projectGuardClerkReady;
    assert.equal(head.clerkLoads, 1);
    console.log('Frontend configuration/session transport checks passed (7 cases).');
})().catch(error => {console.error(error); process.exitCode = 1;});
