const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync('Frontend/auth-retry.js', 'utf8');
const response = (status, detail = '') => ({
    status,
    clone() { return this; },
    async json() { return {detail}; },
});

async function run(replies) {
    const calls = [];
    const delays = [];
    const window = {
        projectGuardApiFetch: async (_url, init) => {
            calls.push(init);
            return replies[calls.length - 1];
        },
    };
    vm.runInNewContext(source, {window, setTimeout: (resolve, delay) => {
        delays.push(delay);
        resolve();
    }});
    const result = await window.projectGuardAuthFetch('/api/me', {method: 'GET'});
    return {result, calls, delays};
}

(async () => {
    const recovered = await run([response(401, 'TOKEN_NOT_ACTIVE_YET'), response(200)]);
    assert.equal(recovered.result.status, 200);
    assert.equal(recovered.calls.length, 2);
    assert.deepEqual(recovered.delays, [1000]);

    const persistent = await run(Array.from({length: 4}, () => response(401, 'TOKEN_NOT_ACTIVE_YET')));
    assert.equal(persistent.result.status, 401);
    assert.equal(persistent.calls.length, 4);
    assert.deepEqual(persistent.delays, [1000, 2000, 4000]);

    const other = await run([response(401, 'TOKEN_EXPIRED')]);
    assert.equal(other.calls.length, 1);
    assert.deepEqual(other.delays, []);
    console.log('Authentication timing retry checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
