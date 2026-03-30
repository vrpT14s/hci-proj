window.ws = new WebSocket("ws://localhost:8765");

//async function load_flamegraph() {
//    let res = await fetch("flamegraph.svg");
//    let svg_text = await res.text();
//
//    document.getElementById("flamegraph").innerHTML = svg_text;
//
//    patch_flamegraph();
//}

//window.onload = function() {
//    load_flamegraph();
//};

window.ws.onmessage = function(event) {
    let msg = JSON.parse(event.data);

    if (msg.type === "callgraph_update") {
        update_callgraph(msg.svg);
    }
	//document.getElementById("callgraph").innerHTML = "hiii"
};

function send_event(type, payload) {
    window.ws.send(JSON.stringify({
        type,
        ...payload
    }));
}

function update_callgraph(svg_text) {
    document.getElementById("callgraph").innerHTML = svg_text;
}

function handle_server_event(msg) {
    if (msg.type === "callgraph_update") {
        update_callgraph(msg.svg);
        //highlight_node(msg.focus);
    }
    if (msg.type === "source") {
        const panel = document.getElementById("gdb_panel");
        panel.textContent = msg.text;  // raw source text
    }
}
