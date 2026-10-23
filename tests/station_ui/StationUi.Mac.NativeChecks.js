ObjC.import('Foundation');
function run(argv) {
    function read(path) {
        return ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError($(path), $.NSUTF8StringEncoding, null));
    }
    var core = eval(read(argv[0] + '/StationUi.Core.js') + '\nStationCore;');
    var texts = JSON.parse(read(argv[0] + '/../station-ui-texts.json'));
    var s = core.state();
    core.apply(s, {schema: 'hubicg.station.event/1', seq: 1, type: 'run_start', data: {steps: ['git']}});
    core.apply(s, {schema: 'hubicg.station.event/1', seq: 3, type: 'run_end', data: {exitCode: 0, steps: {git: 'installed'}}});
    core.complete(s, 0, texts);
    if (s.gaps !== 1 || s.status.git !== 'installed' || !core.summary(s, texts).includes('Relatório incompleto')) {
        throw new Error('Falha no estado do contrato no JXA nativo.');
    }
    if (!core.valid({type: 'email', required: true}, 'maria@exemplo.com.br') ||
            core.valid({type: 'boolean'}, 'true')) { throw new Error('Falha na validação nativa.'); }
    var mismatch = core.state(); mismatch.ended = true; mismatch.exitCode = 0;
    if (core.complete(mismatch, 1, texts).exitCode !== 1 || !mismatch.protocolMismatch) {
        throw new Error('Falha na reconciliação do processo nativo.');
    }
    var incomplete = core.complete(core.state(), 127, texts);
    if (incomplete.exitCode !== 130 || incomplete.processExitCode !== 127) {
        throw new Error('Falha no diagnóstico do protocolo incompleto.');
    }
    var result = {nativeCore: 'ok', guiOpened: false};
    if (argv.indexOf('--capture-preflight') >= 0) {
        try {
            ObjC.import('CoreGraphics');
            ObjC.bindFunction('CGPreflightScreenCaptureAccess', ['bool', []]);
            result.capturePermissionForThisProcess = !!$.CGPreflightScreenCaptureAccess();
        } catch (error) { result.capturePreflightError = String(error); }
    }
    return JSON.stringify(result);
}
