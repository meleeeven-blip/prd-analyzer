from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from src.analyzer import PRDAnalyzer

app = FastAPI(title="PRD Analyzer")

_store: dict[str, dict] = {}
STATIC = Path(__file__).parent / "static"


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        prd_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, detail="文件编码错误，请使用 UTF-8 文本文件")

    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="服务器未配置 DASHSCOPE_API_KEY 环境变量")

    fid = uuid.uuid4().hex[:8]
    try:
        result = PRDAnalyzer(api_key=api_key).analyze(prd_text)
    except Exception as exc:
        raise HTTPException(500, detail=str(exc))

    entry = {
        "id": fid,
        "filename": file.filename or "未命名.md",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "result": result.model_dump(mode="json"),
    }
    _store[fid] = entry
    return entry


@app.get("/api/analyses")
async def list_analyses():
    return sorted(_store.values(), key=lambda x: x["created_at"], reverse=True)


@app.get("/api/analyses/{fid}")
async def get_analysis(fid: str):
    if fid not in _store:
        raise HTTPException(404, detail="找不到该记录")
    return _store[fid]


@app.delete("/api/analyses/{fid}")
async def delete_analysis(fid: str):
    _store.pop(fid, None)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, reload=True)
