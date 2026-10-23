/* Núcleo M1: somente contrato, estado, respostas e textos. Compatível com JXA. */
var StationCore = (function () {
    'use strict';
    function state() {
        return {steps: [], status: {}, messages: {}, actions: [], logs: [], environment: {},
            blocking: null, exitCode: null, ended: false, lastSeq: 0, gaps: 0, recovered: [],
            index: 0, total: 0, current: '', logFile: '', repoDir: ''};
    }
    function apply(s, line) {
        var e;
        try { e = typeof line === 'string' ? JSON.parse(line) : line; } catch (_) { return; }
        if (!e || e.schema !== 'hubicg.station.event/1' || !e.type) { return; }
        var d = e.data || {}, step = e.step || '';
        if (s.lastSeq && e.seq > s.lastSeq + 1) { s.gaps += e.seq - s.lastSeq - 1; }
        s.lastSeq = Math.max(s.lastSeq, e.seq || 0);
        if (e.type === 'run_start') {
            s.steps = (d.steps || []).slice(); s.total = s.steps.length;
            s.repoDir = d.repoDir || ''; s.logFile = d.logFile || ''; s.mode = d.mode;
        } else if (e.type === 'step_start') {
            if (s.steps.indexOf(step) < 0) { s.steps.push(step); }
            s.current = step; s.index = d.index || 0; s.total = d.total || s.total;
        } else if (e.type === 'progress') {
            s.progress = e.message || '';
        } else if (e.type === 'log') {
            s.logs.push({status: e.status, message: e.message || ''});
        } else if (e.type === 'action_required') {
            var a = {id: d.id, kind: d.kind, message: e.message || '', step: step,
                answers: d.answers || [], command: d.command, url: d.url, code: d.code,
                browserOpenedByTool: d.browserOpenedByTool, timeoutSeconds: d.timeoutSeconds};
            if (d.blocking) { s.blocking = a; } else { s.actions.push(a); }
        } else if (e.type === 'action_resolved') {
            s.blocking = null;
        } else if (e.type === 'step_end') {
            if (s.steps.indexOf(step) < 0) { s.steps.push(step); }
            s.status[step] = e.status; s.messages[step] = e.message || '';
            if (step === 'environment') { s.environment = d; }
            if (s.blocking && s.blocking.step === step) { s.blocking = null; }
        } else if (e.type === 'run_end') {
            Object.keys(d.steps || {}).forEach(function (key) {
                if (s.steps.indexOf(key) < 0) { s.steps.push(key); }
                if (s.status[key] !== d.steps[key]) {
                    s.status[key] = d.steps[key]; s.recovered.push(key);
                    s.messages[key] = 'Status recuperado do resumo; detalhes indisponíveis.';
                }
            });
            s.exitCode = d.exitCode; s.ended = true; s.blocking = null;
        }
    }
    function complete(s, code, texts) {
        s.processExitCode = code;
        s.protocolIncomplete = !s.ended;
        s.protocolMismatch = s.ended && s.exitCode !== code;
        if (!s.ended) { s.exitCode = code === 2 || code === 4 ? code : 130; }
        else if ([0, 3, 5].indexOf(s.exitCode) >= 0 && code !== 0 && code !== s.exitCode) {
            s.exitCode = code < 0 || code === 130 ? 130 : 1;
        }
        if ([0, 3, 5].indexOf(s.exitCode) >= 0 && Object.keys(s.status).some(function (key) {
            return !texts.statuses[s.status[key]] || texts.statuses[s.status[key]].group === 'failed';
        })) { s.exitCode = 1; }
        s.ended = true; s.blocking = null;
        return s;
    }
    function selected(s) {
        return s.steps.filter(function (key) { return key !== 'environment' && s.status[key] !== 'unsupported'; });
    }
    function args(mode, only, repo, answers) {
        var result = ['--json', '--non-interactive'];
        if (mode === 'check') { result.unshift('--check'); }
        if (mode === 'plan') { result.unshift('--dry-run'); }
        if (only && only.length) { result.push('--only', only.join(',')); }
        if (repo) { result.push('--repo-dir', repo); }
        if (answers) { result.push('--answers-file', answers); }
        return result;
    }
    function valid(field, value) {
        if (field.type === 'boolean') { return typeof value === 'boolean'; }
        value = String(value).trim();
        if (!value) { return !field.required; }
        return !/[\x00-\x1f\x7f]/.test(value) &&
            (field.type !== 'email' || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value));
    }
    function merge(session, s, texts) {
        s.steps.forEach(function (key) {
            var old = texts.statuses[session.status[key]], next = s.status[key];
            if (old && old.group === 'done' && (next === 'already' || next === 'skipped')) { return; }
            if (next) { session.status[key] = next; session.messages[key] = s.messages[key]; }
        });
        var merged = Object.assign({}, s);
        merged.status = Object.assign({}, session.status); merged.messages = Object.assign({}, session.messages);
        return merged;
    }
    function summary(s, texts) {
        var lines = [texts.exitCodes[String(s.exitCode)] || ('Código de saída: ' + s.exitCode)];
        if (s.protocolIncomplete) {
            lines.push('Relatório incompleto: o motor terminou sem run_end. Código real do processo: ' + s.processExitCode + '.');
        } else if (s.protocolMismatch) {
            lines.push('O evento final e o término do processo divergiram. Código real do processo: ' + s.processExitCode + '.');
        }
        if (s.gaps || s.recovered.length) {
            lines.push(texts.eventWarning.replace('{0}', s.gaps).replace('{1}', s.recovered.length));
        }
        s.steps.forEach(function (key) {
            if (!s.status[key]) { return; }
            var info = texts.statuses[s.status[key]];
            lines.push((texts.steps[key] || key) + ': ' + (info ? info.label : 'Falhou: status desconhecido') +
                '\n' + (s.messages[key] || ''));
        });
        s.logs.filter(function (entry) { return entry.status === 'warn' || entry.status === 'error'; })
            .forEach(function (entry) { lines.push(logText(entry)); });
        if (s.logFile) { lines.push('Log desta execução: ' + s.logFile); }
        return lines.join('\n\n');
    }
    function logText(entry) {
        var label = {info: 'Informação', warn: 'Aviso', error: 'Erro'};
        return (label[entry.status] || entry.status || 'Log') + ': ' + entry.message;
    }
    function environment(s) {
        var d = s.environment, lines = [d.os || '', d.osVersion || '', d.arch || ''];
        lines = [lines.join(' '), 'Gerenciador: ' + (d.packageManager || 'ausente'),
            'TLS: ' + (d.tls || 'não verificado')];
        Object.keys(d.tools || {}).forEach(function (key) { lines.push(key + ': ' + (d.tools[key] || 'ausente')); });
        ['shell', 'shellVersion', 'sudo', 'admin', 'diskFreeGB', 'proxy', 'network'].forEach(function (key) {
            if (d[key] !== undefined && d[key] !== null) {
                lines.push(key + ': ' + (typeof d[key] === 'object' ? JSON.stringify(d[key]) : String(d[key])));
            }
        });
        return lines.concat(s.logs.map(logText)).join('\n');
    }
    return {state: state, apply: apply, complete: complete, selected: selected, args: args,
        valid: valid, merge: merge, summary: summary, environment: environment};
}());
if (typeof module !== 'undefined') { module.exports = StationCore; }
