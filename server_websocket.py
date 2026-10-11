# server_websocket.py - V21 0.2초 WebSocket 푸시 서버 (Render 무료 최적화)
# 실행: uvicorn server_websocket:app --host 0.0.0.0 --port 10000
# Render: Start Command = uvicorn server_websocket:app --host 0.0.0.0 --port $PORT

import asyncio, json, hmac, hashlib, time, os
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException
from fastapi.responses import JSONResponse
import uuid

app = FastAPI(title="MNQ V21 WebSocket Server - 0.2s Copy")

# === 설정 ===
SECRET_KEY = os.getenv("MNQ_SECRET", "mnq_v21_secret_2026_change_this")
EXPIRY_SEC = 10  # 신호 만료 10초
CIRCUIT_LIMIT = 5  # 10초안에 5회 이상이면 STOP
CIRCUIT_WINDOW = 10

# 연결된 클라이언트: user_id -> [websocket]
clients: Dict[str, List[WebSocket]] = defaultdict(list)
# 서킷브레이커용 타임스탬프 기록: user_id -> deque[timestamps]
order_history: Dict[str, deque] = defaultdict(lambda: deque())
# 최근 실행 ID 중복 방지 (서버 차원)
executed_ids = set()
executed_ids_lock = asyncio.Lock()

def make_signature(signal_id: str, signal: str, expire_ts: float) -> str:
    msg = f"{signal_id}:{signal}:{expire_ts}".encode()
    return hmac.new(SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:16]

def verify_signature(signal_id: str, signal: str, expire_ts: float, sign: str) -> bool:
    expected = make_signature(signal_id, signal, expire_ts)
    return hmac.compare_digest(expected, sign)

@app.get("/")
def root():
    return {"status":"ok","version":"V21-0.2s","clients":sum(len(v) for v in clients.values())}

@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now().isoformat()}

# === 관리자 푸시 엔드포인트 ===
@app.post("/api/push")
async def push_signal(payload: dict, x_api_key: str = Header(None)):
    # 간단 API키 체크 (환경변수 MNQ_API_KEY 설정 시)
    required_key = os.getenv("MNQ_API_KEY")
    if required_key and x_api_key != required_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")

    target = payload.get("target", "ALL")  # ALL_COPY or specific USER_1
    signal = payload.get("signal", "").upper()  # BUY / SELL / EXIT / LICENSE
    symbol = payload.get("symbol", "MNQM26")
    user = payload.get("user", "ADMIN")  # 관리자 ID

    if signal not in ["BUY","SELL","EXIT","LICENSE","STOP","START"]:
        return JSONResponse({"error":"invalid signal"}, status_code=400)

    # ID 생성
    signal_id = payload.get("id") or f"{symbol}-{signal}-{int(time.time()*1000)}-{uuid.uuid4().hex[:4]}"
    expire_ts = time.time() + EXPIRY_SEC
    sign = make_signature(signal_id, signal, expire_ts)

    data = {
        "id": signal_id,
        "signal": signal,
        "symbol": symbol,
        "target": target,
        "user": user,
        "expire": expire_ts,
        "expire_human": (datetime.now() + timedelta(seconds=EXPIRY_SEC)).isoformat(),
        "sign": sign,
        "time": datetime.now().isoformat(),
        "payload": payload  # LICENSE일 경우 내부 데이터 포함
    }

    # 서킷브레이커 체크 (서버 차원)
    # target이 ALL이면 전체 카운트, 특정 유저면 해당 유저 카운트
    check_key = target if target != "ALL" else "ALL_COPY"
    dq = order_history[check_key]
    now = time.time()
    # 10초 윈도우 밖 제거
    while dq and now - dq[0] > CIRCUIT_WINDOW:
        dq.popleft()
    dq.append(now)
    if len(dq) >= CIRCUIT_LIMIT + 1:  # 5번 초과시 = 6번째부터 차단
        # STOP 신호 브로드캐스트
        stop_data = {
            "id": f"STOP-CIRCUIT-{int(now*1000)}",
            "signal": "LICENSE",
            "symbol": symbol,
            "target": check_key,
            "payload": {"trading":"STOP","reason":f"CIRCUIT {CIRCUIT_LIMIT} in {CIRCUIT_WINDOW}s"},
            "expire": now + EXPIRY_SEC,
            "sign": make_signature(f"STOP-CIRCUIT-{int(now*1000)}","LICENSE", now+EXPIRY_SEC),
            "time": datetime.now().isoformat()
        }
        await broadcast(stop_data, check_key)
        return {"status":"circuit_break","triggered":True,"count":len(dq),"broadcast_stop":True}

    await broadcast(data, target)
    return {"status":"pushed","id":signal_id,"target":target,"clients":sum(len(v) for v in clients.values())}

async def broadcast(data: dict, target: str):
    # target = ALL or ALL_COPY or USER_1
    to_send = []
    if target in ["ALL","ALL_COPY"]:
        # 모든 연결된 클라이언트에 전송
        for uid, ws_list in clients.items():
            to_send.extend(ws_list)
    else:
        # 특정 유저에게만
        to_send = clients.get(target, [])

    if not to_send:
        return
    msg = json.dumps(data, ensure_ascii=False)
    dead = []
    for ws in to_send:
        try:
            await ws.send_text(msg)
        except:
            dead.append(ws)
    # 죽은 연결 정리
    for ws in dead:
        for uid in list(clients.keys()):
            if ws in clients[uid]:
                clients[uid].remove(ws)

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await websocket.accept()
    clients[user_id].append(websocket)
    print(f"[V21] {user_id} connected. Total: {len(clients[user_id])}")
    try:
        # 연결 유지용 ping 루프 + 클라이언트 메시지 수신 (하트비트)
        while True:
            try:
                # 30초 타임아웃으로 ping 대기
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # 클라이언트에서 보낸 하트비트나 모드 변경 알림 처리
                try:
                    j = json.loads(msg)
                    if j.get("type") == "heartbeat":
                        await websocket.send_text(json.dumps({"type":"pong","time":datetime.now().isoformat()}))
                except:
                    pass
            except asyncio.TimeoutError:
                # 30초마다 서버에서 ping
                try:
                    await websocket.send_text(json.dumps({"type":"ping","time":datetime.now().isoformat()}))
                except:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in clients[user_id]:
            clients[user_id].remove(websocket)
        print(f"[V21] {user_id} disconnected")

# === LICENSE 전용 엔드포인트 (텔레그램 폼 호환) ===
@app.post("/api/license")
async def push_license(payload: dict, x_api_key: str = Header(None)):
    # payload 예: {"user":"USER_1","trading":"STOP","copy":"disabled","daily_loss_limit":-200}
    required_key = os.getenv("MNQ_API_KEY")
    if required_key and x_api_key != required_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    target = payload.get("user","ALL")
    signal_id = f"LICENSE-{target}-{int(time.time()*1000)}"
    expire_ts = time.time() + EXPIRY_SEC
    data = {
        "id": signal_id,
        "signal": "LICENSE",
        "target": target,
        "payload": payload,
        "expire": expire_ts,
        "sign": make_signature(signal_id, "LICENSE", expire_ts),
        "time": datetime.now().isoformat()
    }
    await broadcast(data, target)
    return {"status":"license_pushed","target":target}
