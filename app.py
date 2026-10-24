from flask import Flask, request, jsonify
from flask_cors import CORS
import os, requests, datetime
app = Flask(__name__)
CORS(app)

NPOINT_ID = "3ea328e3dfcf89218a22"
NPOINT_URL = f"https://api.npoint.io/{NPOINT_ID}"
PROFIT_DISCLAIMER = "수수료0.02%(증권사별 다름) + 슬리피지0.5틱 미포함 이기 때문에 정확한 수익은 이용 하고 있는 증권사의 매매집계를 참조 하십시요"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "-1003987555752")

def attach_disclaimer(t):
    if not t: return t
    if "$" in t or "수익" in t:
        if "수수료0.02%" not in t:
            t += f"\n\n※ {PROFIT_DISCLAIMER}"
    return t

def tg_api(m,p=None):
    if not BOT_TOKEN: return {"ok":False}
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{m}"
        r = requests.post(url, json=p, timeout=10) if p else requests.get(url, timeout=10)
        return r.json()
    except Exception as e:
        return {"ok":False,"error":str(e)}

@app.route("/")
def root():
    return jsonify({"ok":True,"npoint":NPOINT_ID,"status":"healthy","disclaimer":PROFIT_DISCLAIMER})

@app.route("/health")
def health():
    return jsonify({"ok":True,"status":"healthy","npoint":NPOINT_ID,"time":datetime.datetime.utcnow().isoformat()})

@app.route("/webhook", methods=["POST","GET"])
def webhook():
    if request.method=="GET":
        return jsonify({"ok":True,"npoint":NPOINT_ID})
    try:
        d = request.get_json(force=True, silent=True) or {}
        msg = d.get("message",{})
        chat = msg.get("chat",{})
        cid = chat.get("id") or CHANNEL_ID
        base = "수익 현황 · 단순 수익률 (복리 아님) · 초기 $10,000 기준\n$2,111,184\n관리자 수익률 +60%\n내 PC 수익률 +54%\n\n⚠️ 1억 전에는 출금 하지 마십시오.\n천오백으로 1년이면 1억 됩니다."
        out = attach_disclaimer(base)
        tg_api("sendMessage",{"chat_id":cid,"text":out})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
