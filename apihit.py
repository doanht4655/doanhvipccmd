import json
import threading
import time
from flask import Flask, jsonify
from websocket import WebSocketApp

# ======================
# 🔗 Biến lưu phiên mới nhất
# ======================
latest_result = {
    "sid": None,
    "md5": None,
    "dices": None,
    "total": None,
    "result": None,
    "timestamp": None
}

WS_URL = "wss://mynygwais.hytsocesk.com/websocket"

# ======================
# 🎧 WebSocket Callbacks
# ======================
def on_open(ws):
    print("[+] WebSocket đã kết nối")

    auth_payload = [
        1,
        "MiniGame",
        "",
        "",
        {
            "agentId": "1",
            "accessToken": "1-a29d6159d76d7dcb02ef52fbdfd21e1d",
            "reconnect": False
        }
    ]
    ws.send(json.dumps(auth_payload))
    print("[>] Đã gửi xác thực")

    def send_cmd():
        time.sleep(1)
        cmd_payload = [
            6,
            "MiniGame",
            "taixiuKCBPlugin",
            {"cmd": 2001}
        ]
        ws.send(json.dumps(cmd_payload))
        print("[>] Đã gửi cmd 2001")
    threading.Thread(target=send_cmd).start()


def on_message(ws, message):
    try:
        data = json.loads(message)

        if isinstance(data, list) and len(data) == 2 and data[0] == 5 and isinstance(data[1], dict):
            payload = data[1]

            if "d" in payload and isinstance(payload["d"], dict):
                d = payload["d"]
                cmd = d.get("cmd")
                sid = d.get("sid")
                md5 = d.get("md5")

                if cmd == 2006 and all(k in d for k in ["d1", "d2", "d3"]):
                    # Có kết quả
                    d1, d2, d3 = d["d1"], d["d2"], d["d3"]
                    total = d1 + d2 + d3
                    result = "Tài" if total >= 11 else "Xỉu"

                    latest_result.update({
                        "sid": sid,
                        "md5": md5,
                        "dices": [d1, d2, d3],
                        "total": total,
                        "result": result,
                        "timestamp": time.time()
                    })

                    print(f"✅ Phiên {sid}: {d1}-{d2}-{d3} = {total} ➜ {result} | MD5: {md5}")

                elif cmd == 2005:
                    # Phiên tiếp theo chưa có kết quả
                    latest_result.update({
                        "sid": sid,
                        "md5": md5,
                        "dices": None,
                        "total": None,
                        "result": None,
                        "timestamp": time.time()
                    })

                    print(f"⏭️ Phiên kế tiếp: {sid} | MD5: {md5} (chưa có kết quả)")

    except Exception as e:
        print("[!] Lỗi xử lý:", e)


def on_error(ws, error):
    print("[!] WebSocket lỗi:", error)

def on_close(ws, close_status_code, close_msg):
    print("[x] WebSocket đã đóng, sẽ tự động reconnect sau 3 giây...")


# ======================
# 🚀 Chạy WebSocket với tự động reconnect
# ======================
def run_ws_forever():
    while True:
        try:
            ws = WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )
            ws.run_forever()
        except Exception as e:
            print(f"[!] Lỗi socket ngoài: {e}")
        print("[*] Đang reconnect lại websocket sau 3 giây...")
        time.sleep(3)

# ======================
# 🌐 Flask API (CHỈ JSON)
# ======================
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "✅ API Tài Xỉu đang hoạt động!"

@app.route("/api/latest", methods=["GET"])
def get_latest():
    result = latest_result.copy()

    # Đảm bảo dices luôn là [None, None, None] nếu chưa có
    if result["dices"] is None:
        result["dices"] = [None, None, None]

    # Hiển thị "Đang đợi kết quả..." nếu chưa có result
    if result["result"] is None:
        result["result"] = "Đang đợi kết quả..."

    return jsonify(result)


# ======================
# 🔧 Main
# ======================
if __name__ == "__main__":
    threading.Thread(target=run_ws_forever, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, threaded=True)