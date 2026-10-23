'use strict';
const assert = require('assert');
const path = require('path');
const fs = require('fs');
const root = path.resolve(__dirname, '../..');
const core = require(path.join(root, 'installers/station/ui/macos/StationUi.Core.js'));
const texts = JSON.parse(fs.readFileSync(path.join(root, 'installers/station/ui/station-ui-texts.json'), 'utf8'));
function event(seq, type, step, status, data) {
    return {schema: 'hubicg.station.event/1', runId: 'fixture', seq, type, step, status, message: '', data: data || {}};
}
let s = core.state();
core.apply(s, 'invalid'); core.apply(s, {schema: 'other/1', type: 'run_end'});
assert.strictEqual(s.lastSeq, 0);
core.apply(s, event(1, 'run_start', '', '', {steps: ['environment', 'git', 'claude-desktop']}));
core.apply(s, event(2, 'step_end', 'environment', 'checked', {os: 'macos', tools: {git: '2.39'}, tls: 'direct'}));
core.apply(s, event(4, 'step_end', 'claude-desktop', 'unsupported'));
core.apply(s, event(5, 'run_end', '', '', {exitCode: 0, steps: {environment: 'checked', git: 'installed', 'claude-desktop': 'unsupported'}}));
core.complete(s, 0, texts);
assert.strictEqual(s.gaps, 1);
assert.deepStrictEqual(s.recovered, ['git']);
assert.deepStrictEqual(core.selected(s), ['git']);
assert(core.summary(s, texts).includes('Relatório incompleto'));
assert(core.environment(s).includes('git: 2.39'));
assert.deepStrictEqual(core.args('check', [], '', ''), ['--check', '--json', '--non-interactive']);
assert.deepStrictEqual(core.args('apply', ['git'], '/x y', '/a.json'),
    ['--json', '--non-interactive', '--only', 'git', '--repo-dir', '/x y', '--answers-file', '/a.json']);
assert(core.valid({type: 'email', required: true}, 'maria@exemplo.com.br'));
assert(!core.valid({type: 'email', required: true}, 'maria'));
assert(!core.valid({type: 'string', required: true}, '\u0000'));
assert(core.valid({type: 'boolean'}, false));
assert(!core.valid({type: 'boolean'}, 'true'));
let session = core.state(); core.merge(session, s, texts);
let rerun = core.state(); rerun.steps = ['git']; rerun.status.git = 'already'; rerun.messages.git = 'já estava';
assert.strictEqual(core.merge(session, rerun, texts).status.git, 'installed');
assert.strictEqual(core.merge(core.state(), rerun, texts).status.git, 'already');
s = core.state(); core.apply(s, event(1, 'step_end', 'git', 'future-status'));
core.apply(s, event(2, 'run_end', '', '', {exitCode: 0, steps: {git: 'future-status'}}));
assert.strictEqual(core.complete(s, 0, texts).exitCode, 1);
assert(core.summary(s, texts).includes('Falhou'));
assert.strictEqual(core.complete(core.state(), -15, texts).exitCode, 130);
assert.strictEqual(core.complete(core.state(), 4, texts).exitCode, 4);
[1, 127].forEach(function (code) {
    const incomplete = core.complete(core.state(), code, texts);
    assert.strictEqual(incomplete.exitCode, 130); // contrato /1: sem run_end é interrupção
    assert.strictEqual(incomplete.processExitCode, code);
    assert(core.summary(incomplete, texts).includes('Código real do processo: ' + code));
});
s = core.state(); s.ended = true; s.exitCode = 0;
assert.strictEqual(core.complete(s, 1, texts).exitCode, 1);
assert(s.protocolMismatch);
assert(core.summary(s, texts).includes('divergiram'));
s = core.state(); s.ended = true; s.exitCode = 0;
assert.strictEqual(core.complete(s, 0, texts).exitCode, 0);
assert.strictEqual(s.protocolMismatch, false);
s = core.state();
core.apply(s, event(1, 'action_required', 'gh-auth', 'action_required',
    {id: 'gh-login', kind: 'browser_code', code: 'FAKE-1234', blocking: true}));
assert.strictEqual(s.blocking.code, 'FAKE-1234');
core.apply(s, event(2, 'action_resolved', 'gh-auth', 'completed', {id: 'gh-login'}));
assert.strictEqual(s.blocking, null);
core.apply(s, event(3, 'action_required', 'claude-cli-auth', 'action_required',
    {id: 'claude-auth-unverified', kind: 'run_in_terminal', command: 'claude auth status'}));
assert.strictEqual(s.actions[0].command, 'claude auth status');
// Avisos por arquivo do apply permanecem visíveis e com sua severidade.
s = core.state();
core.apply(s, {schema: 'hubicg.station.event/1', seq: 1, type: 'log', step: 'agents',
    status: 'warn', message: 'Agente editado preservado: exemplo.md', data: {}});
core.apply(s, {schema: 'hubicg.station.event/1', seq: 2, type: 'log', step: 'agents',
    status: 'error', message: 'Falha ao gravar manifesto', data: {}});
assert(core.summary(s, texts).includes('Aviso: Agente editado preservado: exemplo.md'));
assert(core.summary(s, texts).includes('Erro: Falha ao gravar manifesto'));
assert(core.environment(s).includes('Aviso: Agente editado preservado: exemplo.md'));
// Falha desconhecida prevalece sobre pendência/simulação, preservando interrupções.
[0, 3, 5, 130, 2, 4].forEach(function (code) {
    const run = core.state();
    core.apply(run, event(1, 'step_end', 'git', 'future-status'));
    core.apply(run, event(2, 'step_end', 'gh-auth', 'action_required'));
    core.apply(run, event(3, 'run_end', '', '', {exitCode: code,
        steps: {git: 'future-status', 'gh-auth': 'action_required'}}));
    assert.strictEqual(core.complete(run, code, texts).exitCode, [0, 3, 5].includes(code) ? 1 : code);
    assert(core.summary(run, texts).includes('Falhou: status desconhecido'));
});
console.log('M1 core: contract, actions, answers, summary, recovery and idempotent session OK');
