import asyncio
import contextlib
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile

from aiohttp import WSMsgType, web

BASE = "/app/fnos-qq"
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ["TRIM_PKGVAR"]).resolve()
CACHE = DATA / "installer"
SOCKET = Path(os.environ["TRIM_APPDEST"]) / "app.sock"
LIMIT = 512 * 1024 * 1024
NONCE = secrets.token_hex(24)
state = dict(message="请选择 Linux QQ 安装包。", busy=False, ready=False)
lock = asyncio.Lock()
ready = asyncio.Event()


def install(deb):
    def field(name):
        return subprocess.check_output(["dpkg-deb", "-f", deb, name], stderr=subprocess.DEVNULL,text=True).strip()
    if field("Package") != "linuxqq":
        raise ValueError("所选文件不是 linuxqq Debian 安装包")
    arch = field("Architecture")
    if arch != "amd64":
        raise ValueError(f"架构不匹配：安装包为 {arch}，此应用需要 amd64")
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        root = Path(tmp)
        # Extract the vendor payload as an unprivileged user, without maintainer scripts.
        with deb.open("rb") as package:
            subprocess.run(["dpkg-deb","-x","-",tmp],stdin=package,stderr=subprocess.DEVNULL,check=True)
        vendor = root/"opt/QQ"
        if vendor.resolve()!=vendor or (vendor/"qq").resolve()!=vendor/"qq" or not os.access(vendor/"qq",os.X_OK):
            raise ValueError("安装包缺少 /opt/QQ/qq 可执行文件")
        # A single rename publishes a complete client on first installation.
        dest = DATA / "client"
        if not dest.exists():
            vendor.rename(dest)



async def finish(path):
    state["message"]="正在校验架构并解包…"
    await asyncio.to_thread(install,path)
    if path != CACHE/"linuxqq.deb": path.replace(CACHE/"linuxqq.deb")
    state.update(ready=True,message="安装完成，正在打开 QQ…")
    ready.set()


async def initial():
    cached = CACHE / "linuxqq.deb"
    async with lock:
        if cached.is_file() and not ready.is_set():
            state.update(busy=True, message="正在载入上次选择的安装包…")
            try:
                await finish(cached)
            except Exception:
                state["message"] = "缓存文件无法使用，请重新选择 amd64 安装包。"
            finally:
                state["busy"] = False


@web.middleware
async def guard(req,handler):
    if req.headers.get("X-Trim-Userid")!="1000": raise web.HTTPForbidden()
    return await handler(req)


async def page(req):
    return web.Response(text=(HERE/"setup.html").read_text().replace("__NONCE__",NONCE),content_type="text/html",headers={"Cache-Control":"no-store"})


async def status(req):
    return web.json_response(state,headers={"Cache-Control":"no-store"})


async def transfer(req):
    ws=web.WebSocketResponse(max_msg_size=600*1024)
    await ws.prepare(req)
    try:
        data=await asyncio.wait_for(ws.receive_json(),10)
        if not isinstance(data,dict) or not secrets.compare_digest(str(data.get("nonce","")),NONCE):
            await ws.close(code=1008); return ws
        if lock.locked() or ready.is_set(): raise ValueError("已有安装任务，请稍候")
        async with lock:
            if data.get("op") != "upload":
                raise ValueError("请选择本地安装包")
            size=data.get("size")
            if type(size)!=int or not 0<size<=LIMIT: raise ValueError("请选择 512 MiB 以内的 .deb 文件")
            state.update(busy=True,message="正在接收本地文件…")
            path=CACHE/"upload.part"
            try:
                with path.open("wb") as out:
                    while size:
                        await ws.send_json({"next":True})
                        msg=await asyncio.wait_for(ws.receive(),60)
                        if msg.type!=WSMsgType.BINARY or not 0<len(msg.data)<=size:
                            raise ValueError("上传不完整，请重试")
                        out.write(msg.data);size-=len(msg.data)
                await finish(path)
            finally:
                path.unlink(missing_ok=True);state["busy"]=False
            await ws.send_json({"done":True})
    except Exception as e:
        reason=str(e) if isinstance(e,ValueError) else "文件解析或上传失败，请检查安装包后重试。"
        if not state["busy"]: state["message"]=reason
        with contextlib.suppress(ConnectionError): await ws.send_json({"error":reason})
    finally: await ws.close()
    return ws


async def main():
    if (DATA / "client" / "qq").is_file():
        return
    CACHE.mkdir(mode=0o700, exist_ok=True)
    app=web.Application(middlewares=[guard])
    app.add_routes([web.get(BASE+"/",page),web.get(BASE+"/setup-status",status),web.get(BASE+"/setup-transfer",transfer)])
    runner=web.AppRunner(app)
    await runner.setup()
    SOCKET.unlink(missing_ok=True)
    await web.UnixSite(runner,str(SOCKET)).start()
    job=asyncio.create_task(initial())
    await ready.wait()
    await asyncio.sleep(1)
    job.cancel()
    await runner.cleanup()


if __name__=="__main__":
    asyncio.run(main())
    os.execv("/usr/bin/python3",["python3",str(HERE/"server.py")])
