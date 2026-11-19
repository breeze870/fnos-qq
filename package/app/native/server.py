import asyncio
import contextlib
import json
import os
import shutil
import tempfile
import signal
import secrets
import subprocess
from pathlib import Path

from aiohttp import WSMsgType, web

BASE = "/app/fnos-qq"
HERE = Path(__file__).resolve().parent
STATE = Path(os.environ["TRIM_PKGVAR"]).resolve() / "profiles"
STATE.mkdir(mode=0o700, exist_ok=True)
SOCKET = Path(os.environ["TRIM_APPDEST"]) / "app.sock"
runtime_dirs = {}
INDEX = STATE / "accounts.json"
CSRF = secrets.token_hex(24)
accounts = {}
children = {}
lock = asyncio.Lock()


def save():
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(accounts, ensure_ascii=False))
    tmp.replace(INDEX)


async def stop(key):
    proc = children.pop(key, None)
    if proc is None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), 5)
    except asyncio.TimeoutError:
        pass
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    await proc.wait()
    runtime = runtime_dirs.pop(key, None)
    if runtime:
        shutil.rmtree(runtime, ignore_errors=True)


async def start(key):
    if key in children and children[key].returncode is None:
        return
    await stop(key)
    home = STATE / ("slot" + key)
    home.mkdir(mode=0o700, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="qqnative-", dir="/tmp"))
    runtime_dirs[key] = runtime
    env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
               XDG_DATA_HOME=str(home / ".local/share"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_RUNTIME_DIR=str(runtime), XAUTHORITY=str(runtime / "Xauthority"))
    # Keep app framework secrets outside the desktop process environment.
    env = {k: v for k, v in env.items() if not k.startswith("TRIM_")}
    try:
        children[key] = await asyncio.create_subprocess_exec(
            "dbus-run-session", "--", str(HERE / "instance"), str(STATE.parent / "client/qq"),
            env=env, start_new_session=True)
    except OSError:
        shutil.rmtree(runtime_dirs.pop(key), ignore_errors=True)
        raise


@web.middleware
async def guard(req, handler):
    if req.headers.get("X-Trim-Userid") != "1000":
        raise web.HTTPForbidden()
    return await handler(req)


def state(key):
    p = children.get(key)
    if not p or p.returncode is not None:
        return "已停止"
    return "在线桌面" if (runtime_dirs[key] / "vnc").exists() else "启动中"


async def listing(req):
    return web.json_response([
        dict(id=k, name=v["name"], status=state(k)) for k,v in accounts.items()])


async def control(req):
    # fnOS gates the upgrade. Require the page nonce again before any mutation.
    channel = web.WebSocketResponse(max_msg_size=4096)
    await channel.prepare(req)
    try:
        data = await asyncio.wait_for(channel.receive_json(), 8)
        if not isinstance(data, dict) or not secrets.compare_digest(str(data.get("csrf","")), CSRF):
            await channel.close(code=1008)
            return channel
        async with lock:
            op = data.get("action")
            if op == "add":
                key = str(max(map(int,accounts),default=0)+1)
                accounts[key] = {"name": "账号 " + str(int(key)+1), "running": True}
                save()
                await start(key)
            else:
                key = data.get("id")
                if key not in accounts or op not in ("start","stop"):
                    raise ValueError("未知的账号操作")
                accounts[key]["running"] = op == "start"
                save()
                if op == "start":
                    await start(key)
                else:
                    await stop(key)
        await channel.send_json({"id":key})
    except (OSError, ValueError, subprocess.CalledProcessError, asyncio.TimeoutError):
        await channel.send_json({"error":"桌面操作未完成，请刷新账号列表。"})
    finally:
        await channel.close()
    return channel


async def paired(left, right):
    tasks = [asyncio.create_task(left), asyncio.create_task(right)]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def ws(req):
    key = req.match_info["key"]
    client = web.WebSocketResponse(protocols=["binary"],max_msg_size=0)
    async def frames(src, write):
        async for msg in src:
            if msg.type != WSMsgType.BINARY:
                break
            await write(msg.data)
    if key in accounts:
        for _ in range(100):
            if state(key) != "启动中":
                break
            await asyncio.sleep(.1)
        if state(key) != "在线桌面":
            raise web.HTTPServiceUnavailable()
        reader,writer = await asyncio.open_unix_connection(str(runtime_dirs[key] / "vnc"))
        try:
            await client.prepare(req)
            async def to_browser():
                while chunk := await reader.read(65536):
                    await client.send_bytes(chunk)
            async def to_vnc(chunk):
                writer.write(chunk)
                await writer.drain()
            await paired(frames(client,to_vnc),to_browser())
        finally:
            writer.close()
    else:
        raise web.HTTPNotFound()
    return client


async def page(req):
    return web.Response(text=(HERE / "index.html").read_text().replace("__CSRF_TOKEN__",CSRF),content_type="text/html",headers={"Cache-Control":"no-store"})


async def boot(app):
    if INDEX.exists():
        accounts.update(json.loads(INDEX.read_text()))
    else:
        accounts["0"] = {"name":"账号 1","running":True}
        save()
    for key, row in accounts.items():
        if row["running"]:
            await start(key)


async def shutdown(app):
    await asyncio.gather(*(stop(k) for k in list(children)))


app = web.Application(middlewares=[guard], client_max_size=4096)
app.add_routes([web.get(BASE+"/",page),web.get(BASE+"/accounts",listing),web.get(BASE+"/control",control),
                web.get(BASE+"/ws/{key}",ws)])
app.on_startup.append(boot)
app.on_cleanup.append(shutdown)
if __name__ == "__main__":
    SOCKET.unlink(missing_ok=True)
    web.run_app(app,path=str(SOCKET))
