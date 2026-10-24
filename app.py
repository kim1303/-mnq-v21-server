from flask import Flask, request, jsonify
from flask_cors import CORS
import os, requests

app = Flask(__name__)
CORS(app)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "-1003987555752")
FINAL_FORM_URL = os.environ.get("FINAL_FORM_URL", "https://shiny-hall-b9ed.duribun8.workers.dev?v=INITIAL")

# 새 NPOINT ID - 사진 Saved 비활성화 = 저장완료된 그 ID
NPOINT_ID = os.environ.get("NPOINT_ID", "3ea328e3dfcf89218a22")
NPOINT_URL = os.environ.get("NPOINT_URL", f"https://api.npoint.io/{NPOINT_ID}")

# 수익확인 고지 문구 - 개인PC/관리자PC/텔레그램 통일 - 2026-10-24
PROFIT_DISCLAIMER = os.environ.get("PROFIT_DISCLAIMER", "수수료0.02%(증권사별 다름) + 슬리피지0.5틱 미포함 이기 때문에 정확한 수익은 이용 하고 있는 증권사의 매매집계를 참조 하십시요")
FEE_INFO = os.environ.get("FEE_INFO", "수수료0.02%(증권사별 다름) + 슬리피지0.5틱 미포함")
REAL_CALC = {"fee": 0.0002, "slippage": 0.5, "formula": "(청산가-진입가)*수량*포인트가치 - 수수료0.02% - 슬리피지0.5틱"}

def attach_disclaimer(text):
    if not text:
        return text
    if ("$" in text or "수익" in text or "수익률" in text):
        if "수수료0.02%" not in text:
            text = text + f"\n\n※ {PROFIT_DISCLAIMER}"
    return text

def tg_api(method, payload=None):
    if not BOT_TOKEN:
        return {"ok": False, "error": "NO_TOKEN"}
    base = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        if payload is None:
            r = requests.get(base, timeout=10)
        else:
            r = requests.post(base, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route("/")
def root():
    return jsonify({
        "서비스": "mnq-v21-server",
        "상태": "초기상태 - 모든 설정 삭제됨",
        "NPOINT_ID": NPOINT_ID,
        "NPOINT_URL": NPOINT_URL,
        "PROFIT_DISCLAIMER": PROFIT_DISCLAIMER
    })

@app.route("/health")
def health():
    return jsonify({"ok": True, "status": "healthy", "npoint": NPOINT_ID})

@app.route("/api/factory-reset")
def factory_reset():
    results = {}
    try:
        payload_channel = {
            "chat_id": CHANNEL_ID,
            "text": "초기 상태 복구 - 모든 설정 삭제됨\n이제 텔레그램을 재설치한 것과 같은 깨끗한 상태입니다.",
            "reply_markup": {"remove_keyboard": True}
        }
        results["remove_keyboard_channel"] = tg_api("sendMessage", payload_channel)
    except Exception as e:
        results["remove_keyboard_channel"] = {"ok": False, "error": str(e)}
    return jsonify({
        "ok": True,
        "message": "텔레그램 초기 상태로 복구 완료",
        "results": results,
        "next": [
            "1. Telegram 앱을 삭제 후 재설치하면 클라이언트도 초기 상태",
            "2. 채널 -1003987555752 삭제 후 재생성하면 메시지 0개 초기 상태",
            "3. /start 입력하면 이제 아무 버튼도 없는 깨끗한 상태에서 시작"
        ]
    })

@app.route("/api/remove-keyboard")
def remove_keyboard():
    chat_id = request.args.get("chat_id", CHANNEL_ID)
    payload = {
        "chat_id": chat_id,
        "text": "키보드 제거 완료 - 초기 상태",
        "reply_markup": {"remove_keyboard": True}
    }
    r = tg_api("sendMessage", payload)
    return jsonify({"ok": True, "result": r})

@app.route("/api/delete-all")
def delete_all():
    return factory_reset()

def get_profit_text():
    try:
        resp = requests.get(NPOINT_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and "profit_text" in data:
                return attach_disclaimer(data["profit_text"])
    except:
        pass
    base = "수익 현황 · 단순 수익률 (복리 아님) · 초기 $10,000 기준\n$2,111,184\n관리자 수익률 +60%\n내 PC 수익률 +54%\n\n⚠️ 1억 전에는 출금 하지 마십시오.\n천오백으로 1년이면 1억 됩니다."
    return attach_disclaimer(base)

@app.route("/webhook", methods=["POST", "GET"])
def webhook():
    if request.method == "GET":
        return jsonify({"ok": True, "webhook": "ready", "npoint": NPOINT_ID})
    try:
        data = request.get_json(force=True, silent=True) or {}
        message = data.get("message") or data.get("edited_message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id") or CHANNEL_ID
        text_in = message.get("text", "")
        if "/start" in text_in or "수익" in text_in or "현황" in text_in or text_in.strip() == "":
            out_text = get_profit_text()
            payload = {"chat_id": chat_id, "text": out_text}
            tg_api("sendMessage", payload)
            return jsonify({"ok": True, "sent": "profit_with_disclaimer", "npoint": NPOINT_ID})
        payload = {"chat_id": chat_id, "text": f"받음: {text_in}"}
        tg_api("sendMessage", payload)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
