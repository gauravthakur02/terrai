"""
Infrastructure architecture diagram generator.

Parses .tf files and terraform.tfstate to produce a self-contained
interactive HTML diagram showing resources and their relationships.
Falls back to a terminal ASCII diagram if no HTML output is requested.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Resource categories for grouping + colours ────────────────────────────────

_CATEGORY_MAP = {
    "azurerm_resource_group":       ("Azure", "Resource Group", "#0078D4"),
    "azurerm_virtual_network":      ("Azure", "Networking",    "#0EA5E9"),
    "azurerm_subnet":               ("Azure", "Networking",    "#38BDF8"),
    "azurerm_network_security_group":("Azure","Networking",    "#7DD3FC"),
    "azurerm_public_ip":            ("Azure", "Networking",    "#BAE6FD"),
    "azurerm_network_interface":    ("Azure", "Networking",    "#E0F2FE"),
    "azurerm_storage_account":      ("Azure", "Storage",       "#10B981"),
    "azurerm_storage_container":    ("Azure", "Storage",       "#34D399"),
    "azurerm_virtual_machine":      ("Azure", "Compute",       "#F59E0B"),
    "azurerm_linux_virtual_machine":("Azure", "Compute",       "#FBBF24"),
    "azurerm_windows_virtual_machine":("Azure","Compute",      "#FCD34D"),
    "azurerm_kubernetes_cluster":   ("Azure", "Kubernetes",    "#6366F1"),
    "azurerm_container_registry":   ("Azure", "Containers",    "#8B5CF6"),
    "azurerm_key_vault":            ("Azure", "Security",      "#EC4899"),
    "azurerm_sql_server":           ("Azure", "Database",      "#EF4444"),
    "azurerm_sql_database":         ("Azure", "Database",      "#F87171"),
    "azurerm_cosmosdb_account":     ("Azure", "Database",      "#FCA5A5"),
    "azurerm_app_service":          ("Azure", "App Services",  "#14B8A6"),
    "azurerm_function_app":         ("Azure", "App Services",  "#2DD4BF"),
    "aws_vpc":                      ("AWS",   "Networking",    "#F97316"),
    "aws_subnet":                   ("AWS",   "Networking",    "#FB923C"),
    "aws_instance":                 ("AWS",   "Compute",       "#FBBF24"),
    "aws_s3_bucket":                ("AWS",   "Storage",       "#4ADE80"),
    "aws_rds_instance":             ("AWS",   "Database",      "#F87171"),
    "aws_eks_cluster":              ("AWS",   "Kubernetes",    "#818CF8"),
    "aws_lambda_function":          ("AWS",   "Serverless",    "#A78BFA"),
    "google_compute_instance":      ("GCP",   "Compute",       "#FBBF24"),
    "google_storage_bucket":        ("GCP",   "Storage",       "#34D399"),
    "google_container_cluster":     ("GCP",   "Kubernetes",    "#818CF8"),
    "google_sql_database_instance": ("GCP",   "Database",      "#F87171"),
    "kubernetes_deployment":        ("K8s",   "Workload",      "#6366F1"),
    "kubernetes_service":           ("K8s",   "Service",       "#8B5CF6"),
    "kubernetes_namespace":         ("K8s",   "Namespace",     "#A78BFA"),
}

_DEFAULT_CATEGORY = ("Cloud", "Resource", "#64748B")


@dataclass
class ResourceNode:
    resource_type: str
    resource_name: str
    display_name: str = ""
    attributes: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.resource_type}.{self.resource_name}"

    @property
    def category_info(self) -> tuple[str, str, str]:
        return _CATEGORY_MAP.get(self.resource_type, _DEFAULT_CATEGORY)

    @property
    def cloud(self) -> str:
        return self.category_info[0]

    @property
    def category(self) -> str:
        return self.category_info[1]

    @property
    def colour(self) -> str:
        return self.category_info[2]

    @property
    def icon(self) -> str:
        icons = {
            "Resource Group": "📦", "Networking": "🌐", "Storage": "💾",
            "Compute": "💻", "Database": "🗄️", "Kubernetes": "⎈",
            "Security": "🔐", "App Services": "🚀", "Containers": "🐳",
            "Serverless": "⚡", "Workload": "📋", "Service": "🔌",
            "Namespace": "📁",
        }
        return icons.get(self.category, "🔷")

    @property
    def label(self) -> str:
        return self.display_name or self.resource_name


@dataclass
class ResourceEdge:
    source: str   # resource key
    target: str   # resource key
    label: str = ""


class InfrastructureDiagram:
    """Parse workspace TF/state files and generate an interactive HTML diagram."""

    def __init__(self, workspace_dir: str):
        self.workspace = Path(workspace_dir)

    # ── Parsing ───────────────────────────────────────────────────────────

    def parse_resources(self) -> list[ResourceNode]:
        """Combine resources from state (authoritative) and .tf files."""
        nodes: dict[str, ResourceNode] = {}

        # Try state file first (reflects real deployed state)
        state_file = self.workspace / "terraform.tfstate"
        if state_file.exists():
            nodes.update(self._parse_state(state_file))

        # Overlay/supplement with HCL (catches resources not yet applied)
        for tf_file in sorted(self.workspace.glob("*.tf")):
            for key, node in self._parse_hcl(tf_file).items():
                if key not in nodes:
                    nodes[key] = node

        return list(nodes.values())

    def _parse_state(self, state_file: Path) -> dict[str, ResourceNode]:
        nodes: dict[str, ResourceNode] = {}
        try:
            data = json.loads(state_file.read_text(encoding='utf-8'))
            for res in data.get("resources", []):
                rtype = res.get("type", "")
                rname = res.get("name", "")
                if not rtype or not rname:
                    continue
                attrs: dict = {}
                instances = res.get("instances", [])
                if instances:
                    attrs = instances[0].get("attributes", {})
                display = attrs.get("name") or attrs.get("cluster_name") or rname
                node = ResourceNode(
                    resource_type=rtype,
                    resource_name=rname,
                    display_name=str(display),
                    attributes=attrs,
                )
                nodes[node.key] = node
        except (json.JSONDecodeError, KeyError):
            pass
        return nodes

    def _parse_hcl(self, tf_file: Path) -> dict[str, ResourceNode]:
        nodes: dict[str, ResourceNode] = {}
        text = tf_file.read_text(encoding='utf-8')
        # Match: resource "TYPE" "NAME" {
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text):
            rtype, rname = m.group(1), m.group(2)
            # Try to extract the name attribute from the block
            block_start = m.end()
            depth = 1
            pos = block_start
            while pos < len(text) and depth > 0:
                if text[pos] == "{":
                    depth += 1
                elif text[pos] == "}":
                    depth -= 1
                pos += 1
            block = text[block_start:pos - 1]
            name_m = re.search(r'\bname\s*=\s*"([^"]+)"', block)
            display = name_m.group(1) if name_m else rname
            node = ResourceNode(
                resource_type=rtype,
                resource_name=rname,
                display_name=display,
            )
            nodes[node.key] = node
        return nodes

    def detect_relationships(self, resources: list[ResourceNode]) -> list[ResourceEdge]:
        """Scan .tf files for cross-resource references to build edges."""
        edges: list[ResourceEdge] = []
        seen: set[tuple[str, str]] = set()
        resource_keys = {n.key for n in resources}

        for tf_file in sorted(self.workspace.glob("*.tf")):
            text = tf_file.read_text(encoding='utf-8')
            # Find patterns like: azurerm_resource_group.rg_prod.name
            for m in re.finditer(
                r'([a-z][a-z0-9_]+)\.([a-z][a-z0-9_]+)\.[a-z_]+', text
            ):
                ref_type, ref_name = m.group(1), m.group(2)
                ref_key = f"{ref_type}.{ref_name}"
                if ref_key not in resource_keys:
                    continue
                # Which resource block contains this reference?
                pos = m.start()
                containing = self._find_containing_resource(text, pos, resources)
                if containing and containing.key != ref_key:
                    pair = (containing.key, ref_key)
                    if pair not in seen:
                        seen.add(pair)
                        edges.append(ResourceEdge(
                            source=containing.key,
                            target=ref_key,
                        ))
        return edges

    def _find_containing_resource(
        self, text: str, pos: int, resources: list[ResourceNode]
    ) -> Optional[ResourceNode]:
        """Find which resource block in text contains the given position."""
        best: Optional[tuple[int, ResourceNode]] = None
        for m in re.finditer(r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text):
            if m.start() > pos:
                continue
            rtype, rname = m.group(1), m.group(2)
            node = next((r for r in resources if r.resource_type == rtype and r.resource_name == rname), None)
            if node and (best is None or m.start() > best[0]):
                best = (m.start(), node)
        return best[1] if best else None

    # ── HTML generation ───────────────────────────────────────────────────

    def generate_html(
        self,
        resources: Optional[list[ResourceNode]] = None,
        edges: Optional[list[ResourceEdge]] = None,
    ) -> str:
        if resources is None:
            resources = self.parse_resources()
        if edges is None:
            edges = self.detect_relationships(resources)

        nodes_json = json.dumps([
            {
                "id": n.key, "label": n.label, "type": n.resource_type,
                "category": n.category, "cloud": n.cloud,
                "colour": n.colour, "icon": n.icon,
            }
            for n in resources
        ])
        edges_json = json.dumps([
            {"source": e.source, "target": e.target, "label": e.label}
            for e in edges
        ])
        workspace_name = self.workspace.name

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TerraAI Architecture — {workspace_name}</title>
<style>
:root {{
  --bg:#0B0F18;--surface:#111827;--border:#1E2E44;--text:#DCE8F5;
  --muted:#7094B5;--accent:#00D4A0;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;overflow:hidden;height:100vh;display:flex;flex-direction:column}}
header{{padding:.75rem 1.25rem;background:var(--surface);border-bottom:1px solid var(--border);display:flex;align-items:center;gap:1rem;flex-shrink:0}}
header h1{{font-size:.95rem;font-weight:700}}
header .sub{{font-size:.78rem;color:var(--muted)}}
.controls{{display:flex;gap:.5rem;margin-left:auto}}
button{{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:.3rem .75rem;border-radius:6px;cursor:pointer;font-size:.78rem}}
button:hover{{border-color:var(--accent);color:var(--accent)}}
.legend{{display:flex;gap:1rem;flex-wrap:wrap;padding:.5rem 1.25rem;background:var(--surface);border-bottom:1px solid var(--border);font-size:.72rem}}
.leg-item{{display:flex;align-items:center;gap:.35rem;color:var(--muted)}}
.leg-dot{{width:10px;height:10px;border-radius:50%}}
#canvas-wrap{{flex:1;position:relative;overflow:hidden}}
canvas{{position:absolute;top:0;left:0}}
#tooltip{{position:absolute;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.6rem .9rem;font-size:.78rem;pointer-events:none;display:none;max-width:220px;line-height:1.6}}
#tooltip .tt-type{{color:var(--muted);font-size:.7rem}}
.stats{{padding:.4rem 1.25rem;background:var(--surface);border-top:1px solid var(--border);font-size:.75rem;color:var(--muted);display:flex;gap:1.5rem}}
</style>
</head>
<body>
<header>
  <div>
    <h1>🌍 TerraAI — Architecture Diagram</h1>
    <div class="sub">{workspace_name}</div>
  </div>
  <div class="controls">
    <button onclick="resetView()">⟲ Reset</button>
    <button onclick="fitAll()">⊞ Fit</button>
    <button onclick="downloadSVG()">↓ SVG</button>
  </div>
</header>
<div id="legend" class="legend"></div>
<div id="canvas-wrap"><canvas id="c"></canvas></div>
<div id="tooltip"></div>
<div class="stats" id="stats"></div>
<script>
const RAW_NODES={nodes_json};
const RAW_EDGES={edges_json};

// ── Layout engine ──────────────────────────────────────────────────────
const W=()=>document.getElementById('canvas-wrap').offsetWidth;
const H=()=>document.getElementById('canvas-wrap').offsetHeight;
let NODES=[],EDGES=[],cam={{x:0,y:0,scale:1}};
let drag=null,lastMouse=null,hovered=null;
const NODE_R=42,PAD=20;

function initNodes(){{
  const cols=Math.ceil(Math.sqrt(RAW_NODES.length+1));
  NODES=RAW_NODES.map((n,i)=>{{
    const row=Math.floor(i/cols),col=i%cols;
    return {{...n,x:col*(NODE_R*3)+NODE_R*2,y:row*(NODE_R*3.5)+NODE_R*2,vx:0,vy:0}};
  }});
  EDGES=RAW_EDGES.map(e=>{{
    const s=NODES.find(n=>n.id===e.source);
    const t=NODES.find(n=>n.id===e.target);
    return {{...e,s,t}};
  }}).filter(e=>e.s&&e.t);
}}

// Simple force simulation
function simulate(steps=120){{
  for(let step=0;step<steps;step++){{
    // Repulsion
    for(let i=0;i<NODES.length;i++){{
      for(let j=i+1;j<NODES.length;j++){{
        const dx=NODES[j].x-NODES[i].x, dy=NODES[j].y-NODES[i].y;
        const dist=Math.max(Math.sqrt(dx*dx+dy*dy),1);
        const force=8000/(dist*dist);
        NODES[i].vx-=force*dx/dist; NODES[i].vy-=force*dy/dist;
        NODES[j].vx+=force*dx/dist; NODES[j].vy+=force*dy/dist;
      }}
    }}
    // Attraction (edges)
    for(const e of EDGES){{
      const dx=e.t.x-e.s.x, dy=e.t.y-e.s.y;
      const dist=Math.max(Math.sqrt(dx*dx+dy*dy),1);
      const force=(dist-NODE_R*3.5)*0.04;
      e.s.vx+=force*dx/dist; e.s.vy+=force*dy/dist;
      e.t.vx-=force*dx/dist; e.t.vy-=force*dy/dist;
    }}
    // Centering
    const mx=NODES.reduce((a,n)=>a+n.x,0)/NODES.length;
    const my=NODES.reduce((a,n)=>a+n.y,0)/NODES.length;
    for(const n of NODES){{n.vx+=(mx-n.x)*0.01;n.vy+=(my-n.y)*0.01;}}
    // Apply + dampen
    for(const n of NODES){{
      n.x+=n.vx*0.8; n.y+=n.vy*0.8; n.vx*=0.5; n.vy*=0.5;
    }}
  }}
}}

// ── Render ─────────────────────────────────────────────────────────────
const c=document.getElementById('c');
const ctx=c.getContext('2d');

function resize(){{c.width=W();c.height=H();render();}}

function render(){{
  c.width=W();c.height=H();
  ctx.clearRect(0,0,c.width,c.height);
  ctx.save();
  ctx.translate(cam.x+c.width/2,cam.y+c.height/2);
  ctx.scale(cam.scale,cam.scale);

  // Draw edges
  for(const e of EDGES){{
    const {{s,t}}=e;
    ctx.beginPath();
    ctx.moveTo(s.x,s.y);
    // Bezier
    const mx=(s.x+t.x)/2-((t.y-s.y)*0.2);
    const my=(s.y+t.y)/2+((t.x-s.x)*0.2);
    ctx.quadraticCurveTo(mx,my,t.x,t.y);
    ctx.strokeStyle='rgba(0,212,160,0.25)';
    ctx.lineWidth=1.5/cam.scale;
    ctx.stroke();
    // Arrow
    const angle=Math.atan2(t.y-my,t.x-mx);
    const ax=t.x-Math.cos(angle)*NODE_R*0.95;
    const ay=t.y-Math.sin(angle)*NODE_R*0.95;
    ctx.beginPath();
    ctx.moveTo(ax,ay);
    ctx.lineTo(ax-Math.cos(angle-0.4)*8,ay-Math.sin(angle-0.4)*8);
    ctx.lineTo(ax-Math.cos(angle+0.4)*8,ay-Math.sin(angle+0.4)*8);
    ctx.closePath();
    ctx.fillStyle='rgba(0,212,160,0.4)';
    ctx.fill();
  }}

  // Draw nodes
  for(const n of NODES){{
    const isHovered=n===hovered;
    const r=isHovered?NODE_R*1.1:NODE_R;
    // Shadow
    ctx.shadowColor=n.colour+'55';
    ctx.shadowBlur=isHovered?20:8;
    // Outer circle
    ctx.beginPath();
    ctx.arc(n.x,n.y,r,0,Math.PI*2);
    ctx.fillStyle='#111827';
    ctx.fill();
    ctx.strokeStyle=n.colour;
    ctx.lineWidth=(isHovered?2.5:1.5)/cam.scale;
    ctx.stroke();
    ctx.shadowBlur=0;
    // Inner fill segment
    ctx.beginPath();
    ctx.arc(n.x,n.y,r*0.92,0,Math.PI*2);
    const grad=ctx.createRadialGradient(n.x,n.y-r*0.2,0,n.x,n.y,r);
    grad.addColorStop(0,n.colour+'22');
    grad.addColorStop(1,n.colour+'08');
    ctx.fillStyle=grad;
    ctx.fill();
    // Icon
    ctx.font=`${{Math.round(r*0.55)/cam.scale * cam.scale}}px sans-serif`;
    ctx.textAlign='center';
    ctx.textBaseline='middle';
    ctx.fillText(n.icon,n.x,n.y-r*0.12);
    // Label
    ctx.font=`bold ${{Math.max(9,Math.round(10/cam.scale * cam.scale))}}px -apple-system,sans-serif`;
    ctx.fillStyle=isHovered?'#fff':'#DCE8F5';
    ctx.fillText(clip(n.label,14),n.x,n.y+r*0.45);
    // Category pill
    ctx.font=`${{Math.max(7,Math.round(8/cam.scale * cam.scale))}}px -apple-system,sans-serif`;
    ctx.fillStyle=n.colour+'aa';
    ctx.fillText(n.category,n.x,n.y+r*0.72);
  }}

  ctx.restore();
}}

function clip(s,max){{return s.length>max?s.slice(0,max-1)+'…':s;}}

// ── Legend ─────────────────────────────────────────────────────────────
function buildLegend(){{
  const cats=new Map();
  for(const n of NODES){{
    if(!cats.has(n.category))cats.set(n.category,n.colour);
  }}
  const leg=document.getElementById('legend');
  leg.innerHTML=[...cats.entries()].map(([cat,col])=>
    `<div class="leg-item"><div class="leg-dot" style="background:${{col}}"></div>${{cat}}</div>`
  ).join('');
  document.getElementById('stats').innerHTML=
    `<span>${{NODES.length}} resource${{NODES.length!==1?'s':''}} &nbsp;·&nbsp; ${{EDGES.length}} relationship${{EDGES.length!==1?'s':''}}</span>`+
    `<span>workspace: {workspace_name}</span>`;
}}

// ── Camera ─────────────────────────────────────────────────────────────
function resetView(){{cam={{x:0,y:0,scale:1}};render();}}
function fitAll(){{
  if(!NODES.length)return;
  const xs=NODES.map(n=>n.x),ys=NODES.map(n=>n.y);
  const minX=Math.min(...xs)-NODE_R,maxX=Math.max(...xs)+NODE_R;
  const minY=Math.min(...ys)-NODE_R,maxY=Math.max(...ys)+NODE_R;
  const cw=c.width,ch=c.height;
  const scale=Math.min(cw/(maxX-minX),ch/(maxY-minY),1.5)*0.85;
  cam={{x:-((minX+maxX)/2)*scale,y:-((minY+maxY)/2)*scale,scale}};
  render();
}}

// ── Interaction ────────────────────────────────────────────────────────
function worldPos(e){{
  const rect=c.getBoundingClientRect();
  return {{
    x:(e.clientX-rect.left-c.width/2-cam.x)/cam.scale,
    y:(e.clientY-rect.top-c.height/2-cam.y)/cam.scale
  }};
}}
function nodeAt(x,y){{
  return NODES.find(n=>Math.hypot(n.x-x,n.y-y)<=NODE_R);
}}

c.addEventListener('mousedown',e=>{{
  const p=worldPos(e);
  const n=nodeAt(p.x,p.y);
  if(n){{drag={{node:n,ox:n.x-p.x,oy:n.y-p.y}};}}
  else{{drag={{pan:true}};}}
  lastMouse={{x:e.clientX,y:e.clientY}};
}});
c.addEventListener('mousemove',e=>{{
  const p=worldPos(e);
  if(drag){{
    if(drag.node){{drag.node.x=p.x+drag.ox;drag.node.y=p.y+drag.oy;}}
    else if(drag.pan){{cam.x+=e.clientX-lastMouse.x;cam.y+=e.clientY-lastMouse.y;}}
  }}
  lastMouse={{x:e.clientX,y:e.clientY}};
  const n=nodeAt(p.x,p.y);
  hovered=n||null;
  const tt=document.getElementById('tooltip');
  if(n){{
    tt.style.display='block';
    tt.style.left=(e.clientX+16)+'px';
    tt.style.top=(e.clientY-10)+'px';
    tt.innerHTML=`<div><strong>${{n.icon}} ${{n.label}}</strong></div><div class="tt-type">${{n.type}}</div><div style="color:${{n.colour}};font-size:.7rem">${{n.cloud}} · ${{n.category}}</div>`;
  }}else{{tt.style.display='none';}}
  render();
}});
c.addEventListener('mouseup',()=>{{drag=null;}});
c.addEventListener('mouseleave',()=>{{drag=null;hovered=null;document.getElementById('tooltip').style.display='none';render();}});
c.addEventListener('wheel',e=>{{
  e.preventDefault();
  const factor=e.deltaY<0?1.1:1/1.1;
  cam.scale=Math.max(0.2,Math.min(4,cam.scale*factor));
  render();
}},{{passive:false}});

// ── SVG export ─────────────────────────────────────────────────────────
function downloadSVG(){{
  const lines=[`<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" style="background:#0B0F18">`];
  for(const e of EDGES){{
    const {{s,t}}=e;
    const mx=(s.x+t.x)/2,my=(s.y+t.y)/2;
    lines.push(`<line x1="${{s.x+600}}" y1="${{s.y+400}}" x2="${{t.x+600}}" y2="${{t.y+400}}" stroke="rgba(0,212,160,0.3)" stroke-width="2"/>`);
  }}
  for(const n of NODES){{
    const x=n.x+600,y=n.y+400;
    lines.push(`<circle cx="${{x}}" cy="${{y}}" r="${{NODE_R}}" fill="#111827" stroke="${{n.colour}}" stroke-width="1.5"/>`);
    lines.push(`<text x="${{x}}" y="${{y-4}}" text-anchor="middle" fill="#DCE8F5" font-size="22">${{n.icon}}</text>`);
    lines.push(`<text x="${{x}}" y="${{y+16}}" text-anchor="middle" fill="#DCE8F5" font-size="9" font-family="system-ui">${{n.label}}</text>`);
    lines.push(`<text x="${{x}}" y="${{y+27}}" text-anchor="middle" fill="${{n.colour}}88" font-size="8" font-family="system-ui">${{n.category}}</text>`);
  }}
  lines.push('</svg>');
  const blob=new Blob([lines.join('\\n')],{{type:'image/svg+xml'}});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='terraai-architecture.svg';
  a.click();
}}

// ── Init ───────────────────────────────────────────────────────────────
window.addEventListener('resize',resize);
initNodes();
simulate(200);
buildLegend();
fitAll();
</script>
</body>
</html>"""

    def save(
        self,
        resources: Optional[list[ResourceNode]] = None,
        edges: Optional[list[ResourceEdge]] = None,
        filename: str = "architecture.html",
    ) -> Path:
        if resources is None:
            resources = self.parse_resources()
        if edges is None:
            edges = self.detect_relationships(resources)
        html = self.generate_html(resources, edges)
        out = self.workspace / filename
        out.write_text(html, encoding='utf-8')
        return out

    def ascii_summary(self, resources: list[ResourceNode], edges: list[ResourceEdge]) -> str:
        """Terminal-friendly text summary when HTML is not shown."""
        if not resources:
            return "No resources found in workspace."
        lines = ["Resources:"]
        for n in resources:
            lines.append(f"  {n.icon}  {n.key:<45}  [{n.category}]")
        if edges:
            lines.append("\nRelationships:")
            for e in edges:
                lines.append(f"  {e.source}  →  {e.target}")
        return "\n".join(lines)
