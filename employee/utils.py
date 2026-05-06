import requests
from datetime import datetime

TELEGRAM_BOT_TOKEN = "8015924639:AAE0CeOd8zZ2XQpw-RBrXRAaZU2gF7ocU4o"
TELEGRAM_CHAT_ID = "6439872871"


def sendTelegramAlert(image_path: str, alert_text: str) -> None:
    # Lấy thời gian hiện tại
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    caption = f"🚨 Cảnh báo phát hiện đối tượng lạ!\n\n📅 Thời gian: {timestamp}\n📝 Thông tin: {alert_text}"

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"

    with open(image_path, "rb") as img:
        files = {"photo": img}
        data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption}

        requests.post(url, data=data, files=files)


def send_command_to_esp32(ip_address, device_name, status):
    """Gửi lệnh điều khiển tới ESP32 qua HTTP API."""
    if not ip_address:
        return False

    # Xác định loại thiết bị từ tên
    cmd_type = ""
    name_lower = device_name.lower()
    if any(x in name_lower for x in ["quạt", "quat", "fan"]):
        cmd_type = "fan"
    elif any(x in name_lower for x in ["led", "đèn", "den"]):
        cmd_type = "led"

    if not cmd_type:
        return False

    try:
        # Gửi request tới ESP32 (ví dụ: http://192.168.1.100/control?fan=on)
        url = f"http://{ip_address}/control?{cmd_type}={status}"
        requests.get(url, timeout=2)
        return True
    except Exception as e:
        print(f"❌ Lỗi gửi lệnh tới ESP32 ({ip_address}): {e}")
        return False

