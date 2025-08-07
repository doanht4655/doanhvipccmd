import json
import logging
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify
from websocket import WebSocketApp

# ======================
# 📝 Thiết lập logging
# ======================
# Tạo thư mục logs nếu chưa có
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/taixiu_api.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("TaiXiuAPI")

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
latest_result_lock = threading.Lock()

WS_URL = "wss://mynygwais.hytsocesk.com/websocket"
ws_instance = None
ws_reconnect_count = 0
ws_last_activity = time.time()
is_ws_connected = False

# ======================
# 🎧 WebSocket Callbacks
# ======================
def on_open(ws):
    global is_ws_connected, ws_last_activity, ws_reconnect_count
    is_ws_connected = True
    ws_last_activity = time.time()
    ws_reconnect_count = 0
    logger.info("[+] WebSocket đã kết nối")

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
    logger.info("[>] Đã gửi xác thực")

    def send_cmd():
        time.sleep(1)
        cmd_payload = [
            6,
            "MiniGame",
            "taixiuKCBPlugin",
            {"cmd": 2001}
        ]
        try:
            ws.send(json.dumps(cmd_payload))
            logger.info("[>] Đã gửi cmd 2001")
        except Exception as e:
            logger.error(f"[!] Lỗi gửi cmd: {str(e)}")
    
    threading.Thread(target=send_cmd, daemon=True).start()


def on_message(ws, message):
    global ws_last_activity
    ws_last_activity = time.time()
    
    try:
        data = json.loads(message)

        if isinstance(data, list) and len(data) == 2 and data[0] == 5 and isinstance(data[1], dict):
            payload = data[1]

            if "d" in payload and isinstance(payload["d"], dict):
                d = payload["d"]
                cmd = d.get("cmd")
                sid = d.get("sid")
                md5 = d.get("md5")

                with latest_result_lock:
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

                        logger.info(f"✅ Phiên {sid}: {d1}-{d2}-{d3} = {total} ➜ {result} | MD5: {md5}")

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

                        logger.info(f"⏭️ Phiên kế tiếp: {sid} | MD5: {md5} (chưa có kết quả)")

    except Exception as e:
        logger.error(f"[!] Lỗi xử lý: {str(e)}")


def on_error(ws, error):
    logger.error(f"[!] WebSocket lỗi: {str(error)}")


def on_close(ws, close_status_code, close_msg):
    global is_ws_connected
    is_ws_connected = False
    logger.warning(f"[x] WebSocket đã đóng (code: {close_status_code})")
    
    # Xử lý kết nối lại sẽ được thực hiện bởi watchdog thread
    # Không cần kết nối lại trực tiếp ở đây để tránh recursive


# ======================
# 🚀 Chạy WebSocket
# ======================
def run_ws():
    global ws_instance, is_ws_connected, ws_reconnect_count
    
    try:
        if ws_instance is not None:
            try:
                ws_instance.close()
            except:
                pass
        
        ws_reconnect_count += 1
        logger.info(f"[*] Đang kết nối WebSocket lần {ws_reconnect_count}...")
        
        ws = WebSocketApp(
            WS_URL,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )
        ws_instance = ws
        
        # Khởi động WebSocket trong thread riêng
        wst = threading.Thread(target=lambda: ws.run_forever())
        wst.daemon = True
        wst.start()
        
        return True
    except Exception as e:
        logger.error(f"[!] Lỗi khởi động WebSocket: {str(e)}")
        is_ws_connected = False
        return False


# ======================
# 🔍 Thread giám sát kết nối
# ======================
def watchdog_thread():
    """Thread liên tục kiểm tra và đảm bảo WebSocket kết nối"""
    global ws_last_activity, is_ws_connected, ws_reconnect_count
    
    while True:
        try:
            current_time = time.time()
            # Nếu không hoạt động trong 60 giây hoặc rõ ràng đã mất kết nối
            if (current_time - ws_last_activity > 60) or not is_ws_connected:
                logger.warning("[!] Phát hiện mất kết nối, đang kết nối lại...")
                run_ws()
                
                # Đợi kết nối một thời gian trước khi kiểm tra lại
                time.sleep(10)
            
            # Gửi ping để giữ kết nối Render không ngủ
            if current_time - ws_last_activity > 30 and is_ws_connected and ws_instance:
                try:
                    ws_instance.send("ping")
                    logger.debug("[>] Đã gửi ping để giữ kết nối")
                except:
                    logger.warning("[!] Không thể gửi ping, có thể đã mất kết nối")
                    is_ws_connected = False
            
            # Lưu trạng thái hiện tại để khôi phục nếu có restart
            with latest_result_lock:
                backup_data = latest_result.copy()
            
            try:
                with open("logs/backup.json", "w") as f:
                    json.dump(backup_data, f)
            except Exception as e:
                logger.error(f"[!] Lỗi khi lưu backup: {str(e)}")
            
            # Log trạng thái định kỳ (1 giờ 1 lần)
            if int(current_time) % 3600 < 10:  # Ghi log khi giây trong phạm vi 0-9 của mỗi giờ
                logger.info(f"[*] Hệ thống hoạt động bình thường | WS kết nối: {is_ws_connected}")
                
        except Exception as e:
            logger.error(f"[!] Lỗi trong watchdog: {str(e)}")
        
        # Kiểm tra mỗi 5 giây
        time.sleep(5)


# ======================
# 🌐 Flask API (CHỈ JSON)
# ======================
app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return "✅ API Tài Xỉu đang hoạt động!"

@app.route("/api/latest", methods=["GET"])
def get_latest():
    with latest_result_lock:
        result = latest_result.copy()

    # Đảm bảo dices luôn là [None, None, None] nếu chưa có
    if result["dices"] is None:
        result["dices"] = [None, None, None]

    # Hiển thị "Đang đợi kết quả..." nếu chưa có result
    if result["result"] is None:
        result["result"] = "Đang đợi kết quả..."

    return jsonify(result)

@app.route("/api/health", methods=["GET"])
def health_check():
    """API kiểm tra sức khỏe hệ thống - giúp Render biết ứng dụng còn sống"""
    return jsonify({
        "status": "healthy",
        "ws_connected": is_ws_connected,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@app.route("/api/reconnect", methods=["GET"])
def force_reconnect():
    """API để kích hoạt kết nối lại WebSocket thủ công"""
    success = run_ws()
    return jsonify({
        "success": success,
        "message": "Đã yêu cầu kết nối lại WebSocket",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ======================
# 🔄 Khôi phục dữ liệu
# ======================
def load_backup():
    try:
        backup_file = "logs/backup.json"
        if os.path.exists(backup_file):
            with open(backup_file, "r") as f:
                data = json.load(f)
            
            if isinstance(data, dict) and "sid" in data:
                with latest_result_lock:
                    latest_result.update(data)
                logger.info(f"[+] Đã khôi phục dữ liệu backup | Phiên: {data.get('sid')}")
    except Exception as e:
        logger.error(f"[!] Lỗi khi khôi phục dữ liệu: {str(e)}")


# ======================
# 🔧 Khởi động hệ thống
# ======================
def start_system():
    """Khởi động toàn bộ hệ thống"""
    logger.info("="*50)
    logger.info("🚀 KHỞI ĐỘNG HỆ THỐNG API TÀI XỈU")
    logger.info("="*50)
    
    # Khôi phục dữ liệu backup nếu có
    load_backup()
    
    # Khởi động WebSocket
    run_ws()
    
    # Khởi động thread giám sát
    watchdog = threading.Thread(target=watchdog_thread, daemon=True)
    watchdog.start()
    
    logger.info("[+] Hệ thống đã khởi động hoàn tất")


# ======================
# 🔧 Main
# ======================
# Khởi động hệ thống ngay khi file được import
start_system()

# Cài đặt port từ biến môi trường (Render.com sẽ cung cấp PORT)
port = int(os.environ.get("PORT", 5000))

# Entry point cho Render.com
if __name__ == "__main__":
    # Chạy Flask với port từ biến môi trường
    app.run(host="0.0.0.0", port=port, threaded=True)
