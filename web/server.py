"""TerraAI Web Dashboard — FastAPI server."""
from __future__ import annotations
import asyncio
import json
import queue
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="TerraAI Web", docs_url=None, redoc_url=None)

# Resolve static dir whether running as source or PyInstaller onefile bundle
import sys as _sys
if getattr(_sys, "frozen", False):
    _STATIC = Path(_sys._MEIPASS) / "web" / "static"
else:
    _STATIC = Path(__file__).parent / "static"

# ── Shared runtime state ──────────────────────────────────────────────────────

_config: Any = None
_executor: Any = None
_ws_manager: Any = None
_client: Any = None


def _get_config():
    global _config
    if _config is None:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from config import TerraAIConfig
        _config = TerraAIConfig.load()
    return _config


def _get_executor():
    global _executor, _ws_manager
    from terraform import TerraformExecutor
    from terraform.workspace import WorkspaceManager
    cfg = _get_config()
    ws = cfg.workspace_dir or str(Path.home() / "terraai-workspaces" / "default")
    if _executor is None or str(_executor.workspace_dir) != ws:
        _executor = TerraformExecutor(ws, cfg.terraform_bin)
        _ws_manager = WorkspaceManager(ws)
    return _executor


def _get_ws_manager():
    _get_executor()
    return _ws_manager


def _get_client():
    global _client
    if _client is None:
        from ai import TerraAIClient
        _client = TerraAIClient(_get_config())
    return _client


# ── SSE helpers ───────────────────────────────────────────────────────────────

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _stream_gen(gen_fn):
    """Bridge a sync line-yielding generator to async SSE."""
    q: queue.SimpleQueue = queue.SimpleQueue()

    def _run():
        try:
            for line in gen_fn():
                q.put(line)
        except Exception as exc:
            q.put(f"\n[Error] {exc}\n")
        finally:
            q.put(None)

    threading.Thread(target=_run, daemon=True).start()

    while True:
        line = await asyncio.to_thread(q.get)
        if line is None:
            break
        text = line.rstrip("\n")
        if text:
            yield _sse({"type": "line", "text": text})

    yield _sse({"type": "done"})


# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return HTMLResponse((_STATIC / "index.html").read_text(encoding="utf-8"))


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config():
    cfg = _get_config()
    return {
        "model": cfg.model,
        "workspace_dir": cfg.workspace_dir,
        "provider": cfg.default_provider,
    }


# ── Workspaces ────────────────────────────────────────────────────────────────

@app.get("/api/workspaces")
async def api_workspaces():
    cfg = _get_config()
    current = Path(cfg.workspace_dir or "~").expanduser().resolve()
    parent = current.parent
    workspaces: list[dict] = []
    try:
        for d in sorted(parent.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            tf_files = list(d.glob("*.tf"))
            if tf_files or d.resolve() == current:
                workspaces.append({
                    "name": d.name,
                    "path": str(d),
                    "tf_count": len(tf_files),
                    "active": d.resolve() == current,
                })
    except Exception:
        pass
    if not workspaces:
        workspaces = [{"name": current.name, "path": str(current), "tf_count": 0, "active": True}]
    return {"workspaces": workspaces}


class SwitchReq(BaseModel):
    path: str


@app.post("/api/workspace/switch")
async def api_workspace_switch(req: SwitchReq):
    global _executor, _ws_manager, _client
    cfg = _get_config()
    p = Path(req.path).resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path does not exist")
    cfg.workspace_dir = str(p)
    cfg.save()
    _executor = None
    _ws_manager = None
    _client = None
    return {"ok": True, "workspace": str(p)}


# ── Architecture diagram ──────────────────────────────────────────────────────

@app.get("/api/diagram")
async def api_diagram():
    from vcs.diagram import InfrastructureDiagram
    executor = _get_executor()
    diag = InfrastructureDiagram(str(executor.workspace_dir))
    resources = await asyncio.to_thread(diag.parse_resources)
    edges = await asyncio.to_thread(diag.detect_relationships, resources)
    html = await asyncio.to_thread(diag.generate_html, resources, edges)
    return HTMLResponse(html)


# ── State ─────────────────────────────────────────────────────────────────────

@app.get("/api/state")
async def api_state():
    executor = _get_executor()
    resources_raw = await asyncio.to_thread(executor.list_resources)
    resources = []
    for addr in resources_raw:
        parts = addr.rsplit(".", 1)
        rtype = parts[0] if len(parts) == 2 else addr
        rname = parts[1] if len(parts) == 2 else addr
        provider = rtype.split("_")[0] if "_" in rtype else rtype
        resources.append({"address": addr, "type": rtype, "name": rname, "provider": provider})
    outputs = await asyncio.to_thread(executor.get_outputs)
    tf_files = await asyncio.to_thread(
        lambda: [str(f.relative_to(executor.workspace_dir))
                 for f in _get_ws_manager().get_tf_files()]
    )
    return {"resources": resources, "outputs": outputs, "tf_files": tf_files}


# ── Terraform streams ─────────────────────────────────────────────────────────

@app.get("/api/init")
async def api_init():
    executor = _get_executor()
    return StreamingResponse(
        _stream_gen(executor.init),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@app.get("/api/plan")
async def api_plan():
    executor = _get_executor()
    return StreamingResponse(
        _stream_gen(executor.plan),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


class ApplyReq(BaseModel):
    confirmed: bool = False


@app.post("/api/apply")
async def api_apply(req: ApplyReq):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="Apply requires confirmed=true")
    executor = _get_executor()
    return StreamingResponse(
        _stream_gen(lambda: executor.apply(auto_approve=True)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


# ── Cost ──────────────────────────────────────────────────────────────────────

@app.get("/api/cost")
async def api_cost():
    from terraform.cost import is_available, is_installed, estimate
    from terraform.executor import PLAN_FILE
    if not is_available():
        return {"available": False, "hint": "Set INFRACOST_API_KEY to enable cost estimates"}
    executor = _get_executor()
    plan_path = executor.workspace_dir / PLAN_FILE
    data = await asyncio.to_thread(estimate, executor.workspace_dir, plan_path)
    if not data:
        return {"available": True, "diff": None}
    resources = []
    for proj in data.get("projects", []):
        for res in proj.get("diff", {}).get("resources", []):
            try:
                cost = float(res.get("monthlyCost") or "0")
            except (ValueError, TypeError):
                cost = 0.0
            if cost != 0.0:
                resources.append({"name": res.get("name", ""), "cost": cost})
    resources.sort(key=lambda r: abs(r["cost"]), reverse=True)
    return {
        "available": True,
        "diff": data.get("diffTotalMonthlyCost"),
        "total": data.get("totalMonthlyCost"),
        "resources": resources[:10],
    }


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatReq(BaseModel):
    message: str


@app.post("/api/chat")
async def api_chat(req: ChatReq):
    client = _get_client()
    ws_mgr = _get_ws_manager()
    ctx = await asyncio.to_thread(ws_mgr.get_context)

    async def generate():
        q: queue.SimpleQueue = queue.SimpleQueue()
        result_box: list[Any] = [None]

        def _run():
            try:
                gen = client.ask(req.message, ctx)
                while True:
                    try:
                        delta = next(gen)
                        q.put(("delta", delta))
                    except StopIteration as exc:
                        result_box[0] = exc.value
                        break
            except Exception as exc:
                q.put(("error", str(exc)))
            q.put(None)

        threading.Thread(target=_run, daemon=True).start()

        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                break
            kind, payload = item
            if kind == "delta":
                yield _sse({"type": "delta", "text": payload})
            elif kind == "error":
                yield _sse({"type": "error", "message": payload})

        ai_resp = result_box[0]
        if ai_resp:
            yield _sse({
                "type": "done",
                "hcl": ai_resp.hcl or "",
                "files": [{"path": f["path"], "content": f["content"]}
                           for f in (ai_resp.files or [])],
                "summary": ai_resp.summary or "",
                "warnings": ai_resp.warnings or [],
            })
        else:
            yield _sse({"type": "done", "hcl": "", "files": [], "summary": "", "warnings": []})

    return StreamingResponse(generate(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Save HCL ──────────────────────────────────────────────────────────────────

class SaveReq(BaseModel):
    filename: str
    content: str


@app.post("/api/save")
async def api_save(req: SaveReq):
    ws_mgr = _get_ws_manager()
    path = await asyncio.to_thread(ws_mgr.write_hcl, req.filename, req.content)
    return {"ok": True, "path": str(path)}


# ── Launch ────────────────────────────────────────────────────────────────────

def launch(config=None, host: str = "127.0.0.1", port: int = 7820):
    """Start the TerraAI web server and open browser."""
    global _config
    if config is not None:
        _config = config

    import uvicorn
    import webbrowser

    url = f"http://{host}:{port}"

    def _open():
        import time
        time.sleep(0.9)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()
    print(f"\n  TerraAI Web UI  →  {url}\n  Press Ctrl+C to stop.\n", flush=True)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="warning",
        loop="asyncio",     # skip uvloop — avoids C-extension issues in frozen binary
        http="h11",         # skip httptools — pure Python fallback
    )
