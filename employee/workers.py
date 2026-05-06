import threading
import time
import os
from django.utils import timezone as TZ
from .models import Device, TimeOffDevice
from .utils import send_command_to_esp32

def update_devices_status(room, status):
    """Cập nhật trạng thái thiết bị trong DB và gửi lệnh tới ESP32."""
    devices = Device.objects.filter(room=room)
    devices.update(status=status)
    for d in devices:
        send_command_to_esp32(d.ip_address, d.name, status)

def check_timeoff_devices():
    """Kiểm tra và tắt thiết bị nếu đã hết giờ."""
    # Đợi một chút để database sẵn sàng khi khởi động
    time.sleep(5)
    while True:
        try:
            now = TZ.localtime().time()
            # Lấy tất cả các bản ghi hẹn giờ
            timeoffs = TimeOffDevice.objects.all()
            for toff in timeoffs:
                if toff.time and toff.time <= now:
                    print(f"[Worker] Tự động tắt thiết bị tại phòng {toff.room} (Hết giờ: {toff.time})")
                    update_devices_status(toff.room, "off")
                    toff.delete()
        except Exception as e:
            # Tránh in lỗi liên tục nếu DB chưa sẵn sàng
            print(f"[Worker] Lỗi trong quá trình kiểm tra TimeOff: {e}")
            time.sleep(10)
        
        # Đợi 30 giây trước khi kiểm tra lại
        time.sleep(30)

def start_timeoff_checker():
    """Khởi chạy luồng chạy ngầm."""
    # Trong môi trường dev (runserver), Django chạy 2 process. 
    # RUN_MAIN=true là process thực thi code chính.
    if os.environ.get('RUN_MAIN') == 'true':
        print("[Worker] Đang khởi tạo luồng tự động tắt thiết bị (TimeOffChecker)...")
        thread = threading.Thread(target=check_timeoff_devices, daemon=True)
        thread.start()
