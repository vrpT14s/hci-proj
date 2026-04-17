import * as vscode from 'vscode';
import * as http from 'http';

type BridgePayload =
    | { action: 'select_location'; path: string; line: number }
    | { action: 'select_function'; function: string };

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

export function activate(context: vscode.ExtensionContext) {
    const disposable = vscode.commands.registerCommand('callgraph-profiler.showGraph', async () => {
        const panel = vscode.window.createWebviewPanel(
            'callGraph',
            'Interactive Call Graph',
            vscode.ViewColumn.Two,
            { enableScripts: true }
        );

        const graph = await buildGraphData();
        panel.webview.html = getWebviewContent(graph);

        panel.webview.onDidReceiveMessage(
            async message => {
                if (message.command !== 'openFile') {
                    return;
                }

                try {
                    const uri = vscode.Uri.file(message.file);
                    const doc = await vscode.workspace.openTextDocument(uri);
                    const editor = await vscode.window.showTextDocument(doc, vscode.ViewColumn.One);

                    const line = Number.isFinite(message.line) && message.line > 0 ? message.line - 1 : 0;
                    const position = new vscode.Position(line, 0);

                    editor.selection = new vscode.Selection(position, position);
                    editor.revealRange(new vscode.Range(position, position), vscode.TextEditorRevealType.InCenter);

                    await postBridgeCommand({
                        action: 'select_location',
                        path: uri.fsPath,
                        line: line + 1
                    });
                } catch {
                    vscode.window.showErrorMessage(`Could not open file: ${message.file}`);
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
        }, 180);
    });

    context.subscriptions.push(disposable);
    context.subscriptions.push(pingDisposable);
    context.subscriptions.push(syncDisposable);
    context.subscriptions.push(selectionDisposable);
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

    const symbolTree = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
        'vscode.executeDocumentSymbolProvider',
        uri
    );
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
        const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
            'vscode.executeDocumentSymbolProvider',
            uri
        );
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
    <div id="cy"></div>
    <script>
        const vscode = acquireVsCodeApi();
        const elements = ${JSON.stringify(elements)};

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

        cy.on('tap', 'node', function(evt){
            var node = evt.target;
            vscode.postMessage({
                command: 'openFile',
                file: node.data('file'),
                line: node.data('line')
            });
        });
    </script>
</body>
</html>`;
}

export function deactivate() {}