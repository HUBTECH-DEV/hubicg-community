/* M1: diálogos AppleScript Standard Additions por JXA; Foundation conduz o motor externo. */
ObjC.import('Foundation');
ObjC.import('AppKit');
ObjC.import('stdlib');

function run(argv) {
    'use strict';
    var app = Application.currentApplication(); app.includeStandardAdditions = true;
    var here = argv.shift(), fm = $.NSFileManager.defaultManager;
    function quote(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }
    function read(path) {
        var value = $.NSString.stringWithContentsOfFileEncodingError($(path), $.NSUTF8StringEncoding, null);
        return value ? ObjC.unwrap(value) : '';
    }
    function write(path, text) {
        if (!$(text).writeToFileAtomicallyEncodingError($(path), true, $.NSUTF8StringEncoding, null)) {
            throw new Error('Não foi possível gravar arquivo temporário da interface.');
        }
    }
    var Core = eval(read(here + '/StationUi.Core.js') + '\nStationCore;');
    var texts = JSON.parse(read(here + '/../station-ui-texts.json'));
    var engine = ObjC.unwrap($.NSProcessInfo.processInfo.environment.objectForKey('HUBICG_STATION_ENGINE')) ||
        ObjC.unwrap($(here + '/../../hubicg-station.sh').stringByStandardizingPath);
    var headless = false;
    for (var i = 0; i < argv.length; i++) {
        if (argv[i] === '--engine' && argv[i + 1]) { engine = argv[++i]; }
        else if (argv[i] === '--headless-check') { headless = true; }
        else { throw new Error('Opção desconhecida: ' + argv[i]); }
    }
    function dialog(message, buttons, extra) {
        var options = {withTitle: texts.product, buttons: buttons, defaultButton: buttons[buttons.length - 1]};
        Object.keys(extra || {}).forEach(function (key) { options[key] = extra[key]; });
        return app.displayDialog(message, options);
    }
    function openURL(url) {
        if (url && /^https:\/\//.test(url)) { $.NSWorkspace.sharedWorkspace.openURL($.NSURL.URLWithString($(url))); }
    }
    function remove(path) {
        if (fm.fileExistsAtPath($(path)) && !fm.removeItemAtPathError($(path), null)) {
            throw new Error('Não foi possível limpar o temporário da interface: ' + path);
        }
    }
    var temp = app.doShellScript('umask 077; /usr/bin/mktemp -d /tmp/hubicg-station-ui.XXXXXXXX');
    var active = null;
    function stop() {
        if (!active || !active.isRunning) { return; }
        active.terminate;
        var deadline = Date.now() + 5000;
        while (active.isRunning && Date.now() < deadline) { delay(0.1); }
        if (active.isRunning) { throw new Error('O motor não terminou. Confira o processo antes de continuar.'); }
    }
    function invoke(mode, only, repo, answers) {
        var answerPath = answers && Object.keys(answers).length ? temp + '/answers.json' : '';
        var out = temp + '/stdout.jsonl', err = temp + '/stderr.txt';
        if (answerPath) { write(answerPath, JSON.stringify({schema: 'hubicg.station.answers/1', answers: answers})); }
        write(out, ''); write(err, '');
        app.doShellScript('/bin/chmod 600 ' + [out, err].concat(answerPath ? [answerPath] : []).map(quote).join(' '));
        var task = $.NSTask.alloc.init, output = $.NSFileHandle.fileHandleForWritingAtPath($(out));
        var errors = $.NSFileHandle.fileHandleForWritingAtPath($(err));
        task.launchPath = '/bin/bash';
        task.arguments = $([here + '/StationUi.Process.sh', '/bin/bash', engine].concat(Core.args(mode, only, repo, answerPath)));
        var input = $.NSFileHandle.fileHandleForReadingAtPath('/dev/null');
        task.standardInput = input;
        task.standardOutput = output; task.standardError = errors;
        var s = Core.state(), offset = 0, opened = {}, cancelled = false;
        function consume() {
            var raw = read(out), end = raw.lastIndexOf('\n');
            if (end >= offset) {
                raw.substring(offset, end).split('\n').forEach(function (line) { Core.apply(s, line); });
                offset = end + 1;
            }
        }
        try {
            task.launch; active = task;
            var deadline = Date.now() + (headless ? 180000 : 1800000);
            while (task.isRunning) {
                consume();
                if (Date.now() > deadline) { cancelled = true; stop(); break; }
                if (headless) { delay(0.1); continue; }
                var message = 'Etapa ' + s.index + ' de ' + s.total + ': ' + (texts.steps[s.current] || s.current || 'Iniciando') +
                    '\n\n' + (s.progress || 'Aguarde o motor. Você pode interromper e retomar depois.');
                var buttons = ['Interromper', 'Aguardar'];
                if (s.blocking) {
                    var a = s.blocking;
                    if (a.url && !a.browserOpenedByTool && !opened[a.id]) { openURL(a.url); opened[a.id] = true; }
                    message = a.message + '\n\nCódigo: ' + (a.code || '') + '\nPágina: ' + (a.url || '') +
                        '\n\nO motor continua sozinho quando você autorizar no navegador.';
                    buttons = ['Interromper', 'Copiar código', 'Aguardar'];
                }
                var choice = dialog(message, buttons, {givingUpAfter: 1}).buttonReturned;
                if (choice === 'Interromper') { cancelled = true; stop(); break; }
                if (choice === 'Copiar código' && s.blocking) {
                    $.NSPasteboard.generalPasteboard.clearContents;
                    $.NSPasteboard.generalPasteboard.setStringForType($(s.blocking.code || ''), $.NSPasteboardTypeString);
                }
            }
            task.waitUntilExit; consume();
            Core.complete(s, task.terminationStatus, texts);
            if (cancelled) { s.exitCode = 130; }
            return s;
        } finally {
            try { stop(); } finally {
                input.closeFile; output.closeFile; errors.closeFile; active = null;
                if (answerPath) { remove(answerPath); }
                remove(out); remove(err);
            }
        }
    }
    function actions(list) {
        var answers = {};
        for (var i = 0; i < list.length; i++) {
            var a = list[i], guide = texts.actions[a.id] || texts.kinds[a.kind] || texts.kinds.external;
            if (a.kind === 'input' || a.kind === 'confirm') {
                for (var j = 0; j < a.answers.length; j++) {
                    var f = a.answers[j], value;
                    if (f.type === 'boolean') {
                        value = dialog(guide.guide + '\n\n' + a.message + '\n\n' + f.label,
                            ['Deixar pendente', 'Sim', 'Não']).buttonReturned;
                        if (value !== 'Deixar pendente') { answers[f.key] = value === 'Sim'; }
                    } else {
                        do {
                            var reply = dialog(a.message + '\n\n' + f.label, ['Deixar pendente', 'Continuar'],
                                {defaultAnswer: String(f.default || '')});
                            if (reply.buttonReturned === 'Deixar pendente') { break; }
                            value = reply.textReturned.trim();
                            if (Core.valid(f, value)) { if (value) { answers[f.key] = value; } break; }
                            dialog('Valor inválido. Confira o campo obrigatório e o formato do e-mail.', ['Voltar']);
                        } while (true);
                    }
                }
            } else if (a.kind === 'run_in_terminal' && a.command) {
                if (dialog(guide.guide + '\n\n' + a.message + '\n\nComando oficial: ' + a.command,
                    ['Agora não', 'Abrir terminal']).buttonReturned === 'Abrir terminal') {
                    var launcher = temp + '/login.command';
                    write(launcher, '#!/bin/bash\nexport PATH="$HOME/.local/bin:$PATH"\n' + a.command +
                        '\nprintf "\\nPressione Enter para fechar."\nread -r _\n');
                    app.doShellScript('/bin/chmod 700 ' + quote(launcher) + '; /usr/bin/open -a Terminal ' + quote(launcher));
                    dialog('Conclua o fluxo oficial no terminal. A próxima execução do motor confere o resultado.', ['Entendi']);
                }
            } else {
                var clicked = dialog(guide.guide + '\n\n' + a.message + (a.url ? '\n\n' + a.url : ''),
                    a.url ? ['Deixar pendente', 'Abrir página'] : ['Entendi']).buttonReturned;
                if (clicked === 'Abrir página') { openURL(a.url); }
            }
        }
        return dialog('O motor pode verificar novamente. Nenhum login é confirmado automaticamente.',
            ['Deixar pendente', 'Verificar e continuar']).buttonReturned === 'Verificar e continuar' ? answers : null;
    }
    var result;
    try {
        if (!engine || !fm.fileExistsAtPath($(engine))) { throw new Error('Informe --engine com o caminho do motor externo liberado.'); }
        if (headless) {
            var checked = invoke('check', [], '', null);
            result = {exitCode: checked.exitCode, summary: Core.summary(checked, texts),
                environment: checked.environment, status: checked.status, logFile: checked.logFile,
                processExitCode: checked.processExitCode, protocolIncomplete: checked.protocolIncomplete,
                protocolMismatch: checked.protocolMismatch};
        } else {
            if (dialog(texts.welcome.title + '\n\n' + texts.welcome.body.join('\n\n') + '\n\nMotor: ' + engine,
                ['Cancelar', 'Verificar computador']).buttonReturned === 'Cancelar') { result = {exitCode: 0}; }
            else {
                var check = invoke('check', [], '', null);
                if (check.exitCode === 2 || check.exitCode === 4 || check.exitCode === 130) {
                    dialog(Core.summary(check, texts), ['Fechar']); result = {exitCode: check.exitCode};
                } else if (dialog(Core.environment(check) + '\n\n' + Core.summary(check, texts),
                    ['Cancelar', 'Selecionar etapas']).buttonReturned === 'Cancelar') { result = {exitCode: 0}; }
                else {
                    var available = Core.selected(check), labels = available.map(function (key) { return texts.steps[key] || key; });
                    var selection = app.chooseFromList(labels, {withTitle: texts.product, withPrompt: 'O que instalar',
                        multipleSelectionsAllowed: true, defaultItems: labels, emptySelectionAllowed: false});
                    if (!selection) { result = {exitCode: 0}; }
                    else {
                        var only = available.filter(function (key, index) { return selection.indexOf(labels[index]) >= 0; });
                        if (only.length === available.length) { only = []; }
                        var folder = dialog('Pasta do clone. O motor preserva arquivos existentes.', ['Cancelar', 'Continuar'],
                            {defaultAnswer: check.repoDir || ''});
                        if (folder.buttonReturned === 'Cancelar' || !folder.textReturned.trim()) { result = {exitCode: 0}; }
                        else if (dialog('O motor executará somente as etapas selecionadas.\n\n' +
                            Object.keys(texts.authPreview).map(function (key) { return texts.authPreview[key]; }).join('\n\n'),
                            ['Cancelar', 'Instalar']).buttonReturned === 'Cancelar') { result = {exitCode: 0}; }
                        else {
                            var session = Core.state(), answers = null, state, merged;
                            while (true) {
                                state = invoke('apply', only, folder.textReturned.trim(), answers);
                                merged = Core.merge(session, state, texts);
                                var next = dialog(Core.summary(merged, texts), state.actions.length ?
                                    ['Concluir', 'Rodar de novo', 'Resolver pendências'] : ['Concluir', 'Rodar de novo']).buttonReturned;
                                if (next === 'Concluir') { result = {exitCode: merged.exitCode, status: merged.status, logFile: merged.logFile}; break; }
                                if (next === 'Rodar de novo') { session = Core.state(); answers = null; }
                                else {
                                    answers = actions(state.actions);
                                    if (answers === null) { result = {exitCode: merged.exitCode, status: merged.status, logFile: merged.logFile}; break; }
                                }
                            }
                        }
                    }
                }
            }
        }
    } catch (error) {
        result = {exitCode: error.errorNumber === -128 ? 130 : 1, error: String(error.message || error)};
        if (headless) { result.trace = String(error.stack || ''); }
        if (!headless) { dialog(result.error, ['Fechar']); }
    } finally {
        stop();
        if (/^\/tmp\/hubicg-station-ui\.[A-Za-z0-9]+$/.test(temp)) { remove(temp); }
    }
    ObjC.bindFunction('puts', ['int', ['char *']]);
    $.puts(JSON.stringify(result));
    $.exit(result.exitCode);
}
