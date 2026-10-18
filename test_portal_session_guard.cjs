// Portal access must stay protected when sign-in or the API hangs or starts in <head>.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('Frontend/portal-session-guard.js', 'utf8');
const flush = () => new Promise(resolve => setImmediate(resolve));
const pending = () => {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return {promise, resolve};
};

async function portal(options = {}) {
    const timers = new Map();
    let nextTimer = 0;
    let domReady;
    let requests = 0;
    let reloads = 0;
    const body = {dataset: {portal: 'mentor'}, replaceChildren(panel) { this.panel = panel; }};
    const document = {
        documentElement: {style: {}},
        body: options.inHead ? null : body,
        addEventListener(event, callback) { if (event === 'DOMContentLoaded') domReady = callback; },
        createElement(tag) {
            return {tag, style: {}, children: [], setAttribute() {},
                append(child) { this.children.push(child); },
                addEventListener(event, callback) { this[event] = callback; }};
        },
    };
    const clerk = {session: {getToken: () => options.token || Promise.resolve('fixture-token')}, signOut: async () => {}};
    const window = {
        projectGuardClerkReady: options.ready || Promise.resolve(clerk),
        projectGuardApiBaseUrl: 'http://127.0.0.1:8000',
        projectGuardAuthFetch: async () => {
            requests += 1;
            return options.fetch || {status: options.status || 200, ok: !options.status,
                json: async () => options.json || {role: options.role || 'mentor', identifier: 'fixture'}};
        },
        location: {href: 'http://127.0.0.1:5500/mentor_index.html', reload() { reloads += 1; }, assign() {}},
    };
    vm.runInNewContext(source, {window, document, URL, console: {error() {}},
        setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; },
        clearTimeout(id) { timers.delete(id); },
    });
    await flush();
    return {
        window, document, body, clerk, timers,
        get requests() { return requests; },
        get reloads() { return reloads; },
        finishDocument() { document.body = body; domReady(); },
        async expire() {
            const entry = [...timers].find(([, timer]) => timer.delay === 15000);
            assert.ok(entry, 'An unfinished authentication step must have a timeout');
            timers.delete(entry[0]);
            entry[1].callback();
            await flush();
        },
    };
}

function assertDenied(result, message) {
    assert.equal(result.window.projectGuardProfile, undefined);
    assert.equal(result.document.documentElement.style.visibility, '');
    assert.ok(result.body.panel, 'Replace protected content with an error panel');
    assert.match(result.body.panel.children[0].textContent, message);
}

(async () => {
    const stalledClerk = pending();
    const startup = await portal({ready: stalledClerk.promise});
    assert.equal(startup.document.documentElement.style.visibility, 'hidden');
    await startup.expire();
    assert.equal(await startup.window.projectGuardSessionReady, null);
    assertDenied(startup, /Sign-in services took too long/);
    startup.body.panel.children[1].click();
    assert.equal(startup.reloads, 1);
    stalledClerk.resolve(startup.clerk);
    await flush();
    assert.equal(startup.requests, 0, 'A late Clerk response must not resume a timed-out portal');
    assertDenied(startup, /Sign-in services took too long/);

    const token = await portal({token: pending().promise});
    await token.expire();
    assert.equal(await token.window.projectGuardSessionReady, null);
    assertDenied(token, /session took too long/);
    assert.equal(token.requests, 0);

    const delayedProfile = pending();
    const api = await portal({fetch: delayedProfile.promise});
    await api.expire();
    assert.equal(await api.window.projectGuardSessionReady, null);
    assertDenied(api, /server took too long/);
    delayedProfile.resolve({status: 200, ok: true, json: async () => ({role: 'mentor'})});
    await flush();
    assertDenied(api, /server took too long/);

    const json = await portal({json: pending().promise});
    await json.expire();
    assert.equal(await json.window.projectGuardSessionReady, null);
    assertDenied(json, /server took too long/);

    const mentor = await portal();
    assert.equal(await mentor.window.projectGuardSessionReady, mentor.clerk);
    assert.equal(mentor.window.projectGuardProfile.role, 'mentor');
    assert.equal(mentor.document.documentElement.style.visibility, '');
    assert.equal(mentor.body.panel, undefined);
    assert.equal(mentor.timers.size, 0);

    const student = await portal({role: 'student'});
    assert.equal(await student.window.projectGuardSessionReady, null);
    assertDenied(student, /linked as a student/);

    const rejected = await portal({status: 401});
    assert.equal(await rejected.window.projectGuardSessionReady, null);
    assertDenied(rejected, /rejected this Clerk session/);

    const head = await portal({inHead: true, ready: Promise.reject(new Error('Fixture startup failure'))});
    assert.equal(head.document.documentElement.style.visibility, 'hidden');
    head.finishDocument();
    assert.equal(await head.window.projectGuardSessionReady, null);
    assertDenied(head, /Fixture startup failure/);
    console.log('Portal startup checks passed (8 cases).');
})().catch(error => {console.error(error); process.exitCode = 1;});
