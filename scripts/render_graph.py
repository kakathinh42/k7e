"""Render the knowledge graph to a self-contained, openable HTML file.

Pulls ``GET /graph`` from the running API and writes ``docs/graph-view.html``
with the nodes/edges embedded directly in the page (no live fetch, so no CORS
and no API dependency once generated). Re-run it any time to refresh the
snapshot after new ingests or a backfill.

Usage (stack must be up; API on the compose host port 8001)::

    python scripts/render_graph.py
    python scripts/render_graph.py --api http://localhost:8001 --min-score 0.6

Only the standard library is used, so it runs from anywhere with no install.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>k7e · knowledge graph</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  html,body{margin:0;height:100%;background:#0b1220;color:#e2e8f0;
            font-family:system-ui,sans-serif}
  #bar{padding:10px 16px;border-bottom:1px solid #334155;display:flex;
       gap:18px;align-items:center;flex-wrap:wrap}
  #bar b{color:#fff} .muted{color:#94a3b8;font-size:13px}
  #net{width:100%;height:calc(100vh - 52px)}
  input[type=range]{vertical-align:middle}
  .legend{font-size:12px;color:#94a3b8}
</style></head>
<body>
<div id="bar">
  <b>k7e knowledge graph</b>
  <span class="muted" id="stats"></span>
  <span class="muted">min score
    <input id="thr" type="range" min="0" max="1" step="0.01" value="__MINSCORE__">
    <span id="thrval">__MINSCORE__</span></span>
  <span class="legend">node size = degree · grey = vector similarity · <span style="color:#fbbf24">amber arrow = [[wikilink]]</span> · drag to explore</span>
</div>
<div id="net"></div>
<script>
const DATA = __DATA__;
const palette = ["#38bdf8","#a78bfa","#34d399","#fbbf24","#fb7185","#f472b6","#60a5fa","#4ade80"];
// colour nodes by connected component so clusters are visually obvious
function components(nodes, edges){
  const adj = new Map(nodes.map(n=>[n.id,[]]));
  edges.forEach(e=>{adj.get(e.source)?.push(e.target);adj.get(e.target)?.push(e.source);});
  const comp = new Map(); let c=0;
  for(const n of nodes){ if(comp.has(n.id))continue;
    const stack=[n.id]; comp.set(n.id,c);
    while(stack.length){const x=stack.pop();
      for(const y of (adj.get(x)||[])) if(!comp.has(y)){comp.set(y,c);stack.push(y);}}
    c++; }
  return comp;
}
function build(min){
  const edges = DATA.edges.filter(e=>e.score>=min);
  const live = new Set(); edges.forEach(e=>{live.add(e.source);live.add(e.target);});
  const comp = components(DATA.nodes, edges);
  const nodes = DATA.nodes.map(n=>{
    const deg = edges.reduce((a,e)=>a+(e.source===n.id||e.target===n.id?1:0),0);
    return {id:n.id, label:n.slug, value:Math.max(deg,1),
            title:`${n.title}  (degree ${deg})`,
            color:{background:palette[comp.get(n.id)%palette.length], border:"#0b1220"},
            font:{color:"#e2e8f0"}};
  });
  const eds = edges.map(e=>{
    const explicit = e.origin==="explicit";
    return {from:e.source,to:e.target,value:e.score,
            title:`${explicit?"[[wikilink]]":"similarity "+e.score.toFixed(3)}`,
            dashes:false, arrows: explicit?"to":undefined,
            color:{color: explicit?"#fbbf24":"#475569", opacity: explicit?0.9:0.6}};
  });
  document.getElementById("stats").textContent =
     `${nodes.length} nodes · ${eds.length} edges · ${new Set([...comp.values()]).size} clusters`;
  return {nodes, edges:eds};
}
const container = document.getElementById("net");
let network;
function render(min){
  const {nodes,edges}=build(min);
  network = new vis.Network(container,
    {nodes:new vis.DataSet(nodes), edges:new vis.DataSet(edges)},
    {nodes:{shape:"dot",scaling:{min:8,max:40}},
     edges:{scaling:{min:0.5,max:6},smooth:false},
     physics:{stabilization:true,barnesHut:{springLength:140,gravitationalConstant:-6000}},
     interaction:{hover:true}});
}
render(parseFloat("__MINSCORE__"));
const thr=document.getElementById("thr"), thrval=document.getElementById("thrval");
thr.addEventListener("input",()=>{thrval.textContent=(+thr.value).toFixed(2);render(+thr.value);});
</script>
</body></html>
"""


def fetch_graph(api: str, min_score: float) -> dict:
    url = f"{api.rstrip('/')}/graph?min_score={min_score}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8001")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--out", default="docs/graph-view.html")
    args = ap.parse_args()

    try:
        graph = fetch_graph(args.api, args.min_score)
    except Exception as exc:  # noqa: BLE001 - surface a friendly hint
        print(f"failed to fetch {args.api}/graph: {exc}", file=sys.stderr)
        print("is the stack up?  docker compose up -d api", file=sys.stderr)
        return 1

    html = _TEMPLATE.replace("__DATA__", json.dumps(graph)).replace(
        "__MINSCORE__", str(args.min_score)
    )
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(
        f"wrote {out}  ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)"
        f"  — open it in a browser"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
