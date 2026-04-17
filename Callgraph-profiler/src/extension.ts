import * as vscode from 'vscode';
import * as http from 'http';

type BridgePayload =
    | { action: 'select_location'; path: string; line: number }
    | { action: 'select_function'; function: string };

type ExecutionLocation = {
    file?: string;
    line?: number;
    name?: string;
};

type EditorLocation = {
    file: string;
    line: number;
    name?: string;
};

function hasMeaningfulLocation(loc: ExecutionLocation | undefined): boolean {
    if (!loc) {
        return false;
    }
    return Boolean(loc.file || loc.name || (typeof loc.line === 'number' && loc.line > 0));
}

function getExecutionLocationFromActiveStackItem(): ExecutionLocation | undefined {
    const item = vscode.debug.activeStackItem as unknown as {
        name?: string;
        source?: { uri?: { fsPath?: string } };
        range?: { start?: { line?: number } };
    } | undefined;

    if (!item) {
        return undefined;
    }

    const line0 = item.range?.start?.line;
    return {
        name: item.name,
        file: item.source?.uri?.fsPath,
        line: typeof line0 === 'number' ? line0 + 1 : undefined
    };
}

let selectionSyncTimer: NodeJS.Timeout | undefined;

function getBridgeConfig() {
    const cfg = vscode.workspace.getConfiguration('callgraphProfiler.bridge');
    const enabled = cfg.get<boolean>('enabled', true);
    const host = cfg.get<string>('host', '127.0.0.1');
    const port = cfg.get<number>('port', 8765);
    return { enabled, host, port };
}

function bridgeUrl(pathname: string): string {
    const { host, port } = getBridgeConfig();
    return `http://${host}:${port}${pathname}`;
}

async function postBridgeCommand(payload: BridgePayload): Promise<void> {
    const { enabled, host, port } = getBridgeConfig();
    if (!enabled) {
        return;
    }

    await new Promise<void>((resolve, reject) => {
        const body = JSON.stringify(payload);
        const req = http.request(
            {
                host,
                port,
                path: '/command',
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(body)
                },
                timeout: 1200
            },
            res => {
                const ok = !!res.statusCode && res.statusCode >= 200 && res.statusCode < 300;
                if (ok) {
                    resolve();
                } else {
                    reject(new Error(`Bridge returned status ${res.statusCode ?? 'unknown'}`));
                }
            }
        );

        req.on('timeout', () => {
            req.destroy(new Error('Bridge timeout'));
        });
        req.on('error', reject);
        req.write(body);
        req.end();
    });
}

async function tryPostBridgeCommand(payload: BridgePayload): Promise<void> {
    try {
        await postBridgeCommand(payload);
    } catch {
        // Bridge is optional; ignore connection issues when app is not running.
    }
}

async function pingBridge(): Promise<boolean> {
    const { enabled, host, port } = getBridgeConfig();
    if (!enabled) {
        return false;
    }

    return await new Promise<boolean>((resolve) => {
        const req = http.request(
            {
                host,
                port,
                path: '/health',
                method: 'GET',
                timeout: 1200
            },
            res => {
                resolve(!!res.statusCode && res.statusCode >= 200 && res.statusCode < 300);
            }
        );

        req.on('timeout', () => {
            req.destroy();
            resolve(false);
        });
        req.on('error', () => resolve(false));
        req.end();
    });
}

async function syncEditorLocationToBridge(editor: vscode.TextEditor): Promise<void> {
    if (editor.document.uri.scheme !== 'file') {
        return;
    }

    const line = editor.selection.active.line + 1;
    await postBridgeCommand({
        action: 'select_location',
        path: editor.document.uri.fsPath,
        line
    });
}

function findCallableSymbolAtLine(symbols: vscode.DocumentSymbol[], line: number): vscode.DocumentSymbol | undefined {
    const flat = flattenSymbols(symbols).filter(isCallableSymbol);
    let best: vscode.DocumentSymbol | undefined;

    for (const sym of flat) {
        if (sym.range.start.line <= line && line <= sym.range.end.line) {
            if (!best) {
                best = sym;
                continue;
            }
            const bestSpan = best.range.end.line - best.range.start.line;
            const curSpan = sym.range.end.line - sym.range.start.line;
            if (curSpan <= bestSpan) {
                best = sym;
            }
        }
    }
    return best;
}

async function resolveEditorLocation(editor: vscode.TextEditor): Promise<EditorLocation> {
    const file = editor.document.uri.fsPath;
    const line = editor.selection.active.line + 1;

    let name: string | undefined;
    try {
        const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
            'vscode.executeDocumentSymbolProvider',
            editor.document.uri
        );
        if (symbols && symbols.length > 0) {
            name = findCallableSymbolAtLine(symbols, editor.selection.active.line)?.name;
        }
    } catch {
        // best effort only
    }

    return { file, line, name };
}

async function openFileAtLocation(file: string, oneBasedLine: number): Promise<vscode.TextEditor> {
    const uri = vscode.Uri.file(file);
    const doc = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);

    const line = Number.isFinite(oneBasedLine) && oneBasedLine > 0 ? oneBasedLine - 1 : 0;
    const position = new vscode.Position(line, 0);

    editor.selection = new vscode.Selection(position, position);
    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);
    return editor;
}

function breakpointExists(file: string, oneBasedLine: number): boolean {
    const zeroBased = Math.max(oneBasedLine - 1, 0);
    return vscode.debug.breakpoints.some(bp => {
        if (!(bp instanceof vscode.SourceBreakpoint)) {
            return false;
        }
        return bp.location.uri.fsPath === file && bp.location.range.start.line === zeroBased;
    });
}

function addBreakpointAtLocation(file: string, oneBasedLine: number): void {
    if (breakpointExists(file, oneBasedLine)) {
        return;
    }
    const line = Math.max(oneBasedLine - 1, 0);
    const location = new vscode.Location(vscode.Uri.file(file), new vscode.Position(line, 0));
    const bp = new vscode.SourceBreakpoint(location, true);
    vscode.debug.addBreakpoints([bp]);
}

function removeBreakpointAtLocation(file: string, oneBasedLine: number): void {
    const zeroBased = Math.max(oneBasedLine - 1, 0);
    const toRemove = vscode.debug.breakpoints.filter(bp => {
        if (!(bp instanceof vscode.SourceBreakpoint)) {
            return false;
        }
        return bp.location.uri.fsPath === file && bp.location.range.start.line === zeroBased;
    });

    if (toRemove.length > 0) {
        vscode.debug.removeBreakpoints(toRemove);
    }
}

function toggleBreakpointAtLocation(file: string, oneBasedLine: number): boolean {
    const exists = breakpointExists(file, oneBasedLine);
    if (exists) {
        removeBreakpointAtLocation(file, oneBasedLine);
        return false;
    }

    addBreakpointAtLocation(file, oneBasedLine);
    return true;
}

async function queryExecutionLocation(
    session: vscode.DebugSession,
    preferredThreadId?: number
): Promise<ExecutionLocation | undefined> {
    try {
        const threadsResp = await session.customRequest('threads') as {
            threads?: Array<{ id: number; name: string }>;
        };
        const threads = threadsResp?.threads ?? [];
        if (threads.length === 0) {
            return undefined;
        }

        const thread = threads.find(t => t.id === preferredThreadId) ?? threads[0];
        const stackResp = await session.customRequest('stackTrace', {
            threadId: thread.id,
            startFrame: 0,
            levels: 1
        }) as {
            stackFrames?: Array<{
                name?: string;
                line?: number;
                source?: { path?: string };
            }>;
        };

        const frame = stackResp?.stackFrames?.[0];
        if (!frame) {
            return undefined;
        }

        return {
            name: frame.name,
            line: frame.line,
            file: frame.source?.path
        };
    } catch {
        return undefined;
    }
}

export function activate(context: vscode.ExtensionContext) {
    let graphPanel: vscode.WebviewPanel | undefined;
    let currentExecLocation: ExecutionLocation | undefined;
    let lastStoppedThreadId: number | undefined;

    const postExecLocation = () => {
        if (!graphPanel) {
            return;
        }
        graphPanel.webview.postMessage({
            command: 'execLocation',
            location: currentExecLocation ?? null
        });
    };

    const postEditorLocationToGraph = async (editor?: vscode.TextEditor) => {
        if (!graphPanel) {
            return;
        }
        const activeEditor = editor ?? vscode.window.activeTextEditor;
        if (!activeEditor || activeEditor.document.uri.scheme !== 'file') {
            return;
        }

        const loc = await resolveEditorLocation(activeEditor);
        graphPanel.webview.postMessage({
            command: 'editorLocation',
            location: loc
        });
    };

    const refreshExecutionLocation = async (threadId?: number, session?: vscode.DebugSession) => {
        const fromActiveItem = getExecutionLocationFromActiveStackItem();
        if (hasMeaningfulLocation(fromActiveItem)) {
            currentExecLocation = fromActiveItem;
            postExecLocation();
            return;
        }

        const activeSession = session ?? vscode.debug.activeDebugSession;
        if (!activeSession) {
            currentExecLocation = undefined;
            postExecLocation();
            return;
        }

        const preferredThread = threadId ?? lastStoppedThreadId;
        currentExecLocation = await queryExecutionLocation(activeSession, preferredThread);
        postExecLocation();
    };

    const disposable = vscode.commands.registerCommand('callgraph-profiler.showGraph', async () => {
        const panel = vscode.window.createWebviewPanel(
            'callGraph',
            'Interactive Call Graph',
            vscode.ViewColumn.Two,
            { enableScripts: true }
        );
        graphPanel = panel;
        panel.onDidDispose(() => {
            if (graphPanel === panel) {
                graphPanel = undefined;
            }
        });

        let graph: GraphData;
        try {
            graph = await buildGraphData();
        } catch (error) {
            const msg = error instanceof Error ? error.message : 'Failed to build callgraph.';
            graph = { nodes: [], edges: [], title: `Callgraph unavailable: ${msg}` };
        }
        panel.webview.html = getWebviewContent(graph);
        await refreshExecutionLocation();
        await postEditorLocationToGraph(vscode.window.activeTextEditor ?? undefined);

        panel.webview.onDidReceiveMessage(
            async message => {
                try {
                    switch (message.command) {
                        case 'openFile': {
                            const editor = await openFileAtLocation(message.file, message.line);
                            await tryPostBridgeCommand({
                                action: 'select_location',
                                path: editor.document.uri.fsPath,
                                line: Math.max(Number(message.line) || 1, 1)
                            });
                            return;
                        }
                        case 'setBreakpoint': {
                            const enabled = toggleBreakpointAtLocation(message.file, message.line);
                            panel.webview.postMessage({
                                command: 'breakpointState',
                                file: message.file,
                                line: message.line,
                                exists: enabled
                            });
                            vscode.window.showInformationMessage(
                                enabled
                                    ? `Breakpoint set at ${message.file}:${message.line}`
                                    : `Breakpoint removed at ${message.file}:${message.line}`
                            );
                            await tryPostBridgeCommand({
                                action: 'select_location',
                                path: message.file,
                                line: Math.max(Number(message.line) || 1, 1)
                            });
                            return;
                        }
                        case 'queryBreakpoint': {
                            const exists = breakpointExists(message.file, message.line);
                            panel.webview.postMessage({
                                command: 'breakpointState',
                                file: message.file,
                                line: message.line,
                                exists
                            });
                            return;
                        }
                        case 'revealEditor': {
                            await postEditorLocationToGraph(vscode.window.activeTextEditor ?? undefined);
                            return;
                        }
                        default:
                            return;
                    }
                } catch (error) {
                    const msg = error instanceof Error ? error.message : 'Action failed.';
                    vscode.window.showErrorMessage(msg);
                }
            },
            undefined,
            context.subscriptions
        );
    });

    const pingDisposable = vscode.commands.registerCommand('callgraph-profiler.pingBridge', async () => {
        const ok = await pingBridge();
        if (ok) {
            vscode.window.showInformationMessage(`Python app bridge is reachable at ${bridgeUrl('/health')}`);
        } else {
            vscode.window.showWarningMessage(
                `Python app bridge is not reachable at ${bridgeUrl('/health')}. Start render.py first.`
            );
        }
    });

    const syncDisposable = vscode.commands.registerCommand('callgraph-profiler.syncSelectionToApp', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor) {
            vscode.window.showWarningMessage('No active editor to sync.');
            return;
        }

        try {
            await syncEditorLocationToBridge(editor);
            vscode.window.showInformationMessage('Synced editor location to Python app.');
        } catch {
            vscode.window.showWarningMessage(
                `Could not sync to app bridge at ${bridgeUrl('/command')}. Is render.py running?`
            );
        }
    });

    const setBreakpointCursorDisposable = vscode.commands.registerCommand('callgraph-profiler.setBreakpointAtCursor', async () => {
        const editor = vscode.window.activeTextEditor;
        if (!editor || editor.document.uri.scheme !== 'file') {
            vscode.window.showWarningMessage('No active file editor.');
            return;
        }

        const file = editor.document.uri.fsPath;
        const line = editor.selection.active.line + 1;
        addBreakpointAtLocation(file, line);
        vscode.window.showInformationMessage(`Breakpoint set at ${file}:${line}`);
    });

    const revealEditorDisposable = vscode.commands.registerCommand('callgraph-profiler.revealEditorInGraph', async () => {
        await postEditorLocationToGraph(vscode.window.activeTextEditor ?? undefined);
    });

    const selectionDisposable = vscode.window.onDidChangeTextEditorSelection(async (evt) => {
        if (selectionSyncTimer) {
            clearTimeout(selectionSyncTimer);
        }

        selectionSyncTimer = setTimeout(async () => {
            try {
                await syncEditorLocationToBridge(evt.textEditor);
            } catch {
                // Ignore transient bridge failures for passive sync.
            }

            try {
                await postEditorLocationToGraph(evt.textEditor);
            } catch {
                // Ignore passive graph sync errors.
            }
        }, 180);
    });

    const debugStartDisposable = vscode.debug.onDidStartDebugSession(async (session) => {
        await refreshExecutionLocation(undefined, session);
    });

    const debugChangeDisposable = vscode.debug.onDidChangeActiveDebugSession(async (session) => {
        await refreshExecutionLocation(undefined, session ?? undefined);
    });

    const debugTerminateDisposable = vscode.debug.onDidTerminateDebugSession(async (session) => {
        if (vscode.debug.activeDebugSession === session || !vscode.debug.activeDebugSession) {
            currentExecLocation = undefined;
            postExecLocation();
        }
    });

    const debugCustomEventDisposable = vscode.debug.onDidReceiveDebugSessionCustomEvent(async (evt) => {
        if (evt.event === 'stopped') {
            const body = evt.body as { threadId?: number } | undefined;
            lastStoppedThreadId = body?.threadId;
            await refreshExecutionLocation(body?.threadId, evt.session);
        } else if (evt.event === 'continued') {
            await refreshExecutionLocation(undefined, evt.session);
        }
    });

    const stackItemDisposable = vscode.debug.onDidChangeActiveStackItem(async () => {
        await refreshExecutionLocation();
    });

    context.subscriptions.push(disposable);
    context.subscriptions.push(pingDisposable);
    context.subscriptions.push(syncDisposable);
    context.subscriptions.push(setBreakpointCursorDisposable);
    context.subscriptions.push(revealEditorDisposable);
    context.subscriptions.push(selectionDisposable);
    context.subscriptions.push(debugStartDisposable);
    context.subscriptions.push(debugChangeDisposable);
    context.subscriptions.push(debugTerminateDisposable);
    context.subscriptions.push(debugCustomEventDisposable);
    context.subscriptions.push(stackItemDisposable);
}

type GraphNode = {
    id: string;
    label: string;
    file: string;
    line: number;
};

type GraphEdge = {
    id: string;
    source: string;
    target: string;
};

type GraphData = {
    nodes: GraphNode[];
    edges: GraphEdge[];
    title: string;
};

function nodeId(item: vscode.CallHierarchyItem): string {
    return `${item.uri.fsPath}:${item.selectionRange.start.line}:${item.name}`;
}

function symbolNodeId(uri: vscode.Uri, sym: vscode.DocumentSymbol): string {
    return `${uri.fsPath}:${sym.selectionRange.start.line}:${sym.name}`;
}

function isCallableSymbol(sym: vscode.DocumentSymbol): boolean {
    return sym.kind === vscode.SymbolKind.Function || sym.kind === vscode.SymbolKind.Method;
}

function flattenSymbols(symbols: vscode.DocumentSymbol[]): vscode.DocumentSymbol[] {
    const out: vscode.DocumentSymbol[] = [];
    const walk = (list: vscode.DocumentSymbol[]) => {
        for (const sym of list) {
            out.push(sym);
            if (sym.children.length > 0) {
                walk(sym.children);
            }
        }
    };
    walk(symbols);
    return out;
}

async function buildCallHierarchyGraph(editor: vscode.TextEditor): Promise<GraphData | null> {
    const uri = editor.document.uri;

    let symbolTree: vscode.DocumentSymbol[] | undefined;
    try {
        symbolTree = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
            'vscode.executeDocumentSymbolProvider',
            uri
        );
    } catch {
        return null;
    }
    if (!symbolTree || symbolTree.length === 0) {
        return null;
    }

    const callable = flattenSymbols(symbolTree).filter(isCallableSymbol).slice(0, 30);
    if (callable.length === 0) {
        return null;
    }

    const nodes = new Map<string, GraphNode>();
    const edges = new Map<string, GraphEdge>();

    for (const sym of callable) {
        const items = await vscode.commands.executeCommand<vscode.CallHierarchyItem[]>(
            'vscode.prepareCallHierarchy',
            uri,
            sym.selectionRange.start
        );
        if (!items || items.length === 0) {
            continue;
        }

        for (const item of items) {
            const srcId = nodeId(item);
            nodes.set(srcId, {
                id: srcId,
                label: item.name,
                file: item.uri.fsPath,
                line: item.selectionRange.start.line + 1
            });

            const outgoing = await vscode.commands.executeCommand<vscode.CallHierarchyOutgoingCall[]>(
                'vscode.provideOutgoingCalls',
                item
            );
            if (!outgoing) {
                continue;
            }

            for (const call of outgoing) {
                const target = call.to;
                const dstId = nodeId(target);

                nodes.set(dstId, {
                    id: dstId,
                    label: target.name,
                    file: target.uri.fsPath,
                    line: target.selectionRange.start.line + 1
                });

                const eId = `${srcId}->${dstId}`;
                edges.set(eId, {
                    id: eId,
                    source: srcId,
                    target: dstId
                });
            }
        }
    }

    if (nodes.size === 0) {
        return null;
    }

    return {
        nodes: Array.from(nodes.values()),
        edges: Array.from(edges.values()),
        title: `Calls from ${vscode.workspace.asRelativePath(uri)}`
    };
}

async function buildSymbolFallbackGraph(): Promise<GraphData> {
    const files = await vscode.workspace.findFiles(
        '**/*.{py,js,ts,tsx,java,c,cc,cpp,h,hpp,cs,go,rs}',
        '**/{node_modules,.git,out,dist,build,Callgraph-profiler}/**',
        60
    );

    const nodes = new Map<string, GraphNode>();
    const edges = new Map<string, GraphEdge>();

    for (const uri of files) {
        let symbols: vscode.DocumentSymbol[] | undefined;
        try {
            symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
                'vscode.executeDocumentSymbolProvider',
                uri
            );
        } catch {
            continue;
        }
        if (!symbols || symbols.length === 0) {
            continue;
        }

        const flat = flattenSymbols(symbols).filter(isCallableSymbol).slice(0, 10);
        for (const sym of flat) {
            const id = symbolNodeId(uri, sym);
            nodes.set(id, {
                id,
                label: `${sym.name}()` ,
                file: uri.fsPath,
                line: sym.selectionRange.start.line + 1
            });
        }

        for (let i = 1; i < flat.length; i++) {
            const prev = symbolNodeId(uri, flat[i - 1]);
            const curr = symbolNodeId(uri, flat[i]);
            const eid = `${prev}->${curr}`;
            edges.set(eid, { id: eid, source: prev, target: curr });
        }
    }

    return {
        nodes: Array.from(nodes.values()),
        edges: Array.from(edges.values()),
        title: 'Workspace function graph (fallback)'
    };
}

async function buildGraphData(): Promise<GraphData> {
    const editor = vscode.window.activeTextEditor;
    if (editor) {
        const callGraph = await buildCallHierarchyGraph(editor);
        if (callGraph && callGraph.nodes.length > 0) {
            return callGraph;
        }
    }

    const fallback = await buildSymbolFallbackGraph();
    if (fallback.nodes.length > 0) {
        return fallback;
    }

    return {
        nodes: [],
        edges: [],
        title: 'No symbols found. Open a source file and run again.'
    };
}

function getWebviewContent(graph: GraphData) {
    const elements = [
        ...graph.nodes.map(n => ({ data: n })),
        ...graph.edges.map(e => ({ data: e }))
    ];

    return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.26.0/cytoscape.min.js"></script>
    <style>
        body { margin: 0; padding: 0; overflow: hidden; background-color: #1e1e1e; }
        #cy { width: 100vw; height: 100vh; display: block; }
    </style>
</head>
<body>
    <div id="title" style="position:fixed;top:8px;left:8px;z-index:10;color:#ddd;font-family:sans-serif;font-size:12px;">${graph.title}</div>
    <div id="toolbar" style="position:fixed;top:30px;left:8px;z-index:10;display:flex;gap:8px;align-items:center;background:#252526;border:1px solid #333;border-radius:8px;padding:8px;">
        <button id="openBtn" disabled>Open</button>
        <button id="bpBtn" disabled>Set Breakpoint</button>
        <button id="revealBtn">Reveal Editor</button>
        <span id="selInfo" style="color:#ddd;font-family:sans-serif;font-size:12px;max-width:65vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></span>
    </div>
    <div id="execInfo" style="position:fixed;top:68px;left:8px;z-index:10;color:#ddd;font-family:sans-serif;font-size:12px;background:#252526;border:1px solid #333;border-radius:8px;padding:6px 8px;">
        Current debug frame: (none)
    </div>
    <div id="cy"></div>
    <script>
        const vscode = acquireVsCodeApi();
        const elements = ${JSON.stringify(elements)};
        let selectedNode = null;
        let execLocation = null;
        let editorLocation = null;

        function normalizeName(name) {
            if (!name) return '';
            return String(name)
                .replace(/\(.*\)$/, '')
                .replace(/^.*::/, '')
                .trim();
        }

        function refreshBreakpointButton() {
            const btn = document.getElementById('bpBtn');
            if (!selectedNode) {
                btn.textContent = 'Set Breakpoint';
                return;
            }
            btn.textContent = selectedNode.hasBreakpoint ? 'Remove Breakpoint' : 'Set Breakpoint';
        }

        var cy = cytoscape({
            container: document.getElementById('cy'),
            elements: elements,
            style: [
                {
                    selector: 'node',
                    style: {
                        'background-color': '#007acc',
                        'label': 'data(label)',
                        'color': '#fff',
                        'text-valign': 'center',
                        'text-halign': 'center',
                        'shape': 'round-rectangle',
                        'width': '120px',
                        'height': '40px'
                    }
                },
                {
                    selector: 'edge',
                    style: {
                        'width': 3,
                        'line-color': '#ccc',
                        'target-arrow-color': '#ccc',
                        'target-arrow-shape': 'triangle',
                        'curve-style': 'bezier'
                    }
                }
            ],
            layout: { name: elements.some(e => e.data.source) ? 'cose' : 'grid', fit: true, padding: 40 }
        });

        function applyExecutionHighlight() {
            cy.nodes().removeClass('current-exec');
            const info = document.getElementById('execInfo');

            if (!execLocation) {
                info.textContent = 'Current debug frame: (none)';
                return;
            }

            const name = execLocation.name || '(unknown)';
            const file = execLocation.file || '(no file)';
            const line = execLocation.line || '?';
            info.textContent = 'Current debug frame: ' + name + ' — ' + file + ':' + line;

            let bestNode = null;
            let bestScore = Number.POSITIVE_INFINITY;

            cy.nodes().forEach(n => {
                const nodeFile = String(n.data('file') || '');
                const execFile = String(execLocation.file || '');
                const nodeLine = Number(n.data('line') || 0);
                const execLine = Number(execLocation.line || 0);

                const sameFile = execFile && nodeFile && (
                    nodeFile === execFile ||
                    nodeFile.split('/').pop() === execFile.split('/').pop()
                );
                const sameName = normalizeName(execLocation.name) &&
                    normalizeName(n.data('label')) === normalizeName(execLocation.name);

                if (!sameFile && !sameName) {
                    return;
                }

                let score = 0;
                if (sameFile) {
                    score += 0;
                    if (execLine > 0 && nodeLine > 0) {
                        score += Math.abs(nodeLine - execLine);
                    }
                } else {
                    score += 500;
                }

                if (sameName) {
                    score -= 100;
                } else {
                    score += 50;
                }

                if (score < bestScore) {
                    bestScore = score;
                    bestNode = n;
                }
            });

            if (bestNode) {
                bestNode.addClass('current-exec');
            }
        }

        function applyEditorFocus() {
            cy.nodes().removeClass('editor-focus');
            if (!editorLocation) {
                return;
            }

            const targetFile = String(editorLocation.file || '');
            const targetLine = Number(editorLocation.line || 0);
            const targetName = normalizeName(editorLocation.name);

            let bestNode = null;
            let bestScore = Number.POSITIVE_INFINITY;

            cy.nodes().forEach(n => {
                const nodeFile = String(n.data('file') || '');
                const nodeLine = Number(n.data('line') || 0);
                const nodeName = normalizeName(n.data('label'));

                const sameFile = targetFile && (nodeFile === targetFile || nodeFile.split('/').pop() === targetFile.split('/').pop());
                const sameName = targetName && nodeName === targetName;

                if (!sameFile && !sameName) {
                    return;
                }

                let score = 0;
                if (sameFile) {
                    score += Math.abs(nodeLine - targetLine);
                } else {
                    score += 1000;
                }
                if (!sameName) {
                    score += 25;
                }

                if (score < bestScore) {
                    bestScore = score;
                    bestNode = n;
                }
            });

            if (bestNode) {
                bestNode.addClass('editor-focus');
                setSelected({
                    label: bestNode.data('label'),
                    file: bestNode.data('file'),
                    line: bestNode.data('line'),
                    hasBreakpoint: false
                });
                cy.animate({ center: { eles: bestNode }, duration: 200 });
            }
        }

        function setSelected(node) {
            selectedNode = node;
            document.getElementById('openBtn').disabled = !selectedNode;
            document.getElementById('bpBtn').disabled = !selectedNode;
            refreshBreakpointButton();
            document.getElementById('selInfo').textContent = selectedNode
                ? (selectedNode.label + ' — ' + selectedNode.file + ':' + selectedNode.line)
                : '';

            if (selectedNode) {
                vscode.postMessage({
                    command: 'queryBreakpoint',
                    file: selectedNode.file,
                    line: selectedNode.line
                });
            }
        }

        window.addEventListener('message', event => {
            const message = event.data;
            if (!message) {
                return;
            }

            if (message.command === 'execLocation') {
                execLocation = message.location;
                applyExecutionHighlight();
                return;
            }

            if (message.command === 'editorLocation') {
                editorLocation = message.location;
                applyEditorFocus();
                return;
            }

            if (message.command !== 'breakpointState') {
                return;
            }

            if (
                selectedNode &&
                selectedNode.file === message.file &&
                Number(selectedNode.line) === Number(message.line)
            ) {
                selectedNode.hasBreakpoint = !!message.exists;
                refreshBreakpointButton();
            }
        });

        document.getElementById('openBtn').addEventListener('click', () => {
            if (!selectedNode) return;
            vscode.postMessage({
                command: 'openFile',
                file: selectedNode.file,
                line: selectedNode.line
            });
        });

        document.getElementById('bpBtn').addEventListener('click', () => {
            if (!selectedNode) return;
            vscode.postMessage({
                command: 'setBreakpoint',
                file: selectedNode.file,
                line: selectedNode.line
            });
        });

        document.getElementById('revealBtn').addEventListener('click', () => {
            vscode.postMessage({ command: 'revealEditor' });
        });

        cy.on('tap', 'node', function(evt){
            var node = evt.target;
            setSelected({
                label: node.data('label'),
                file: node.data('file'),
                line: node.data('line'),
                hasBreakpoint: false
            });
        });

        cy.on('dbltap', 'node', function(evt){
            var node = evt.target;
            vscode.postMessage({
                command: 'openFile',
                file: node.data('file'),
                line: node.data('line')
            });
        });

        cy.style()
            .selector('node.current-exec')
            .style({
                'background-color': '#f39c12',
                'border-width': 3,
                'border-color': '#f1c40f'
            })
            .selector('node.editor-focus')
            .style({
                'border-width': 4,
                'border-color': '#2ecc71'
            })
            .update();
    </script>
</body>
</html>`;
}

export function deactivate() {}