import cv2
import numpy as np
import threading
import time
from ultralytics import YOLO
from django.utils import timezone as TZ
from employee.models import IPCamera, Attendance, Device, TimeOffDevice, CalendarEvent
from Auth_app.models import Users
from facerecognition import FacialRecognition
from Auth_app.views import make_safe_filename
from employee.utils import sendTelegramAlert
from employee.workers import update_devices_status
import os
from datetime import timedelta

import torch

currentPythonFilePath = os.getcwd()

# Kiểm tra GPU
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[System] Đang sử dụng thiết bị: {device}")

# Khởi tạo mô hình YOLO và chuyển sang GPU nếu có
yolo_model = YOLO("yolo26n.pt")
if device == "cuda":
    yolo_model.to("cuda")
YOLO_LOCK = threading.Lock()

STREAM_WIDTH = 400
TARGET_PROCESS_FPS = 7
JPEG_QUALITY = 70
MJPEG_READ_TIMEOUT = 5.0
MAX_MJPEG_BUFFER = 1024 * 1024
MAX_RECOGNITION_ATTEMPTS = 5
RECOGNITION_RETRY_SECONDS = 1.2

detector = FacialRecognition.FaceDetector(
    minsize=20,
    threshold=[0.6, 0.7, 0.7],
    factor=0.709,
    gpu_memory_fraction=0.6,
    detect_face_model_path=os.path.join(currentPythonFilePath, "static/align"),
    facenet_model_path=os.path.join(
        currentPythonFilePath, "static/Models/20180402-114759.pb"
    ),
)

recognizer = FacialRecognition.FaceRecognition(
    classifier_path=os.path.join(currentPythonFilePath, "static/Models/facemodel.pkl")
)


class HTTPVideoCapture:
    def __init__(self, url):
        import urllib.request

        self.url = url
        self.stream = None
        self.bytes_buf = bytearray()
        self.latest_frame = None
        self.latest_seq = 0
        self.last_read_seq = -1
        self.lock = threading.Lock()
        self.running = False
        self.thread = None
        try:
            self.stream = urllib.request.urlopen(url, timeout=MJPEG_READ_TIMEOUT)
            self.running = True
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            print(f"[HTTPVideoCapture] Error opening {url}: {e}")

    def isOpened(self):
        return self.stream is not None and self.running

    def _reader_loop(self):
        while self.running:
            try:
                chunk = self.stream.read(8192)
                if not chunk:
                    break

                self.bytes_buf.extend(chunk)
                latest_jpg = None

                while True:
                    start = self.bytes_buf.find(b"\xff\xd8")
                    end = (
                        self.bytes_buf.find(b"\xff\xd9", start + 2)
                        if start != -1
                        else -1
                    )
                    if start == -1 or end == -1:
                        break
                    latest_jpg = bytes(self.bytes_buf[start : end + 2])
                    del self.bytes_buf[: end + 2]

                if len(self.bytes_buf) > MAX_MJPEG_BUFFER:
                    del self.bytes_buf[: len(self.bytes_buf) - MAX_MJPEG_BUFFER]

                if latest_jpg:
                    frame = cv2.imdecode(
                        np.frombuffer(latest_jpg, dtype=np.uint8), cv2.IMREAD_COLOR
                    )
                    if frame is not None:
                        with self.lock:
                            self.latest_frame = frame
                            self.latest_seq += 1
            except Exception as e:
                if self.running:
                    # Only print if it's not a common timeout to avoid spam
                    if "timed out" not in str(e).lower():
                        print(f"[HTTPVideoCapture] Reader Error ({self.url}): {e}")
                break

        self.running = False

    def read(self):
        if not self.isOpened():
            return False, None

        deadline = time.monotonic() + MJPEG_READ_TIMEOUT
        while self.running and time.monotonic() < deadline:
            with self.lock:
                if (
                    self.latest_frame is not None
                    and self.latest_seq != self.last_read_seq
                ):
                    self.last_read_seq = self.latest_seq
                    return True, self.latest_frame.copy()
            time.sleep(0.01)

        return False, None

    def get_latest(self):
        with self.lock:
            if self.latest_frame is None:
                return False, None
            return True, self.latest_frame.copy()

    def release(self):
        self.running = False
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)


class CvVideoCapture:
    def __init__(self, url):
        self.cap = cv2.VideoCapture(url)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

    def isOpened(self):
        return self.cap.isOpened()

    def read(self):
        return self.cap.read()

    def release(self):
        self.cap.release()


def open_video_capture(url):
    url_lower = url.lower()
    if url_lower.startswith("http://") or url_lower.startswith("https://"):
        return HTTPVideoCapture(url)
    return CvVideoCapture(url)


# Bộ nhớ chung cho người lạ để đồng bộ ID giữa các cam
GLOBAL_Unknown_REGISTRY = []  # Lưu: {"emb": embedding, "id": Unknown_id}
Unknown_COUNTER = 0
Unknown_LOCK = threading.Lock()


class CamWorker:
    def __init__(self, cam_id):
        self.cam_id = cam_id
        self.is_running = False
        self.thread = None
        self.current_frame = None
        self.frame_seq = 0
        self.frame_time = 0.0
        self.frame_lock = threading.Lock()
        self.last_db_refresh = 0.0

        # Tracking dictionaries
        self.track_history = {}  # track_id -> "Tên người" hoặc Unknown_X
        self.unknown_counter = {}  # track_id -> số lần suspect (cho Telegram)
        self.recognition_attempts = {}  # track_id -> số lần đã thử nhận diện
        self.recognition_last_try = {}  # track_id -> thời điểm thử nhận diện gần nhất
        self.recognition_in_progress = set()  # track_id đang được xử lý bởi thread khác
        self.recognition_lock = threading.Lock()

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self.run)
            self.thread.daemon = True
            self.thread.start()

    def stop(self):
        self.is_running = False

    def publish_frame(self, frame):
        ok, buffer = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        if ok:
            with self.frame_lock:
                self.current_frame = buffer.tobytes()
                self.frame_seq += 1
                self.frame_time = time.monotonic()

    def get_frame(self):
        with self.frame_lock:
            if self.current_frame is None:
                return None
            return self.frame_seq, self.current_frame, self.frame_time

    def process_person_crop(self, person_img, cam_obj, now):
        rgb_crop = cv2.cvtColor(person_img, cv2.COLOR_BGR2RGB)
        faces, _ = detector.get_faces(rgb_crop)

        for face in faces:
            x1, y1, x2, y2 = list(map(int, face[:4]))
            face_only = rgb_crop[y1:y2, x1:x2]
            if face_only.size == 0:
                continue

            embeddings = detector.get_embeddings(face_only).reshape(1, -1)
            username, prob = recognizer.recognize_face(embeddings)

            if username and prob >= 0.7:
                return username

            # --- Xử lý đồng bộ ID người lạ (Global Re-ID) ---
            global Unknown_COUNTER
            target_emb = embeddings[0]

            with Unknown_LOCK:
                best_match_id = None
                best_dist = 100.0

                for item in GLOBAL_Unknown_REGISTRY:
                    # Tính khoảng cách Euclidean
                    dist = np.linalg.norm(target_emb - item["emb"])
                    # Ngưỡng 0.9 là an toàn cho FaceNet
                    if dist < 0.9 and dist < best_dist:
                        best_dist = dist
                        best_match_id = item["id"]

                if best_match_id is not None:
                    return f"Unknown_{best_match_id}"
                else:
                    Unknown_COUNTER += 1
                    new_id = Unknown_COUNTER
                    GLOBAL_Unknown_REGISTRY.append({"emb": target_emb, "id": new_id})
                    # Giới hạn 100 người lạ
                    if len(GLOBAL_Unknown_REGISTRY) > 100:
                        GLOBAL_Unknown_REGISTRY.pop(0)
                    return f"Unknown_{new_id}"

        return None

    def _async_recognize(self, person_crop, track_id, cam_obj, now):
        try:
            username = self.process_person_crop(person_crop, cam_obj, now)

            with self.recognition_lock:
                self.recognition_attempts[track_id] = (
                    self.recognition_attempts.get(track_id, 0) + 1
                )

                if username:
                    # --- LOGIC TEST: Giả lập người lạ ---
                    # (Giữ nguyên logic của bạn: nếu là Le Tuan Dung thì coi như Unknown để test alert)
                    if username == "Le Tuan Dung":
                        username = None

                if username:
                    self.track_history[track_id] = username
                    # Điểm danh
                    if cam_obj.attendance_enabled:
                        if cam_obj.cam_type == "IN":
                            self.log_attendance_in(username, now)
                        else:
                            self.log_attendance_out(username, now)
        except Exception as e:
            print(f"[CamWorker] Async Recognition Error: {e}")
        finally:
            with self.recognition_lock:
                if track_id in self.recognition_in_progress:
                    self.recognition_in_progress.remove(track_id)

    def log_attendance_in(self, username, now):
        today = now.date()
        user_obj = Users.objects.filter(
            user__username=make_safe_filename(username)
        ).first()
        if not user_obj:
            return

        if user_obj.roll == "Student":
            schedule = CalendarEvent.objects.filter(
                date=today,
                Class=user_obj.Class,
                start_time__lte=now.time(),
                end_time__gte=now.time(),
            ).first()

            if schedule:
                print(f"[CamWorker] Tìm thấy lịch học: {schedule.title} cho {username}")
                attendance, created = Attendance.objects.get_or_create(
                    emcode=user_obj.emcode,
                    date=today,
                    subject=schedule.title,
                    defaults={
                        "name": user_obj.full,
                        "checkin": now.time(),
                        "checkout": None,
                    },
                )
                if created:
                    print(
                        f"[CamWorker] Điểm danh VÀO thành công cho sinh viên: {user_obj.full}"
                    )

                update_devices_status(schedule.room, "on")
                TimeOffDevice.objects.update_or_create(
                    room=schedule.room, defaults={"time": schedule.end_time}
                )
            else:
                print(
                    f"[CamWorker] Không tìm thấy lịch học phù hợp cho {username} (Lớp: {user_obj.Class})"
                )
        elif user_obj.roll in ["Teacher", "Admin"]:
            shift = "Sáng" if now.hour < 12 else "Chiều"
            timeoff_auto = (now + timedelta(hours=4, minutes=30)).time()

            attendance_qs = Attendance.objects.filter(
                emcode=user_obj.emcode, date=today, shift=shift
            )

            if attendance_qs.exists():
                attendance = attendance_qs.first()
                if not attendance.checkin:
                    attendance.checkin = now.time()
                    attendance.save()
                    print(f"[CamWorker] Cập nhật checkin cho GV/Admin: {user_obj.full}")
            else:
                Attendance.objects.create(
                    emcode=user_obj.emcode,
                    name=user_obj.full,
                    date=today,
                    shift=shift,
                    checkin=now.time(),
                )
                print(f"[CamWorker] Điểm danh VÀO mới cho GV/Admin: {user_obj.full}")

            update_devices_status(user_obj.Class, "on")
            TimeOffDevice.objects.update_or_create(
                room=user_obj.Class, defaults={"time": timeoff_auto}
            )

    def log_attendance_out(self, username, now):
        today = now.date()
        user_obj = Users.objects.filter(
            user__username=make_safe_filename(username)
        ).first()
        if not user_obj:
            return

        if user_obj.roll == "Student":
            schedule = CalendarEvent.objects.filter(
                date=today, Class=user_obj.Class, end_time__lte=now.time()
            ).last()

            if schedule:
                attendance_qs = Attendance.objects.filter(
                    emcode=user_obj.emcode, date=today, subject=schedule.title
                )
                if attendance_qs.exists():
                    attendance = attendance_qs.first()
                    if attendance.checkout is None:
                        attendance.checkout = now.time()
                        attendance.save()

        elif user_obj.roll in ["Teacher", "Admin"]:
            shift = "Sáng" if now.hour < 12 else "Chiều"
            attendance_qs = Attendance.objects.filter(
                emcode=user_obj.emcode, date=today, shift=shift
            )
            if attendance_qs.exists():
                attendance = attendance_qs.first()
                if attendance.checkout is None:
                    attendance.checkout = now.time()
                    attendance.save()

    def run(self):
        try:
            cam_obj = IPCamera.objects.get(pk=self.cam_id)
        except IPCamera.DoesNotExist:
            self.is_running = False
            return

        cap = open_video_capture(cam_obj.ip_address)

        if not cap.isOpened():
            print(f"Không thể mở luồng cam {cam_obj.ip_address}")
            self.is_running = False
            return

        while self.is_running:
            loop_started = time.monotonic()

            # Refresh settings every ~10 seconds
            if loop_started - self.last_db_refresh >= 10:
                try:
                    cam_obj.refresh_from_db()
                    self.last_db_refresh = loop_started
                except Exception:
                    pass

            ret, frame = cap.read()
            if not ret:
                if not cap.isOpened():
                    cap.release()
                    time.sleep(1)
                    cap = open_video_capture(cam_obj.ip_address)
                else:
                    time.sleep(0.05)
                continue

            # Giảm độ phân giải để xử lý mượt hơn
            # Resize về chiều rộng cố định, giữ nguyên tỷ lệ
            h, w = frame.shape[:2]
            new_w = STREAM_WIDTH
            new_h = int(h * (new_w / w))
            frame = cv2.resize(frame, (new_w, new_h))
            if not cam_obj.attendance_enabled and not cam_obj.tracking_enabled:
                self.publish_frame(frame)
                time.sleep(
                    max(0, (1 / TARGET_PROCESS_FPS) - (time.monotonic() - loop_started))
                )
                continue

            now = TZ.localtime(TZ.now())

            # YOLO tracking với ByteTrack để ID ổn định hơn
            # imgsz=320 giúp xử lý cực nhanh trên CPU
            # Skip frame logic: Chỉ xử lý YOLO mỗi 2 frame để giảm tải CPU
            if self.frame_seq % 2 == 0:
                with YOLO_LOCK:
                    results = yolo_model.track(
                        frame,
                        classes=[0],
                        persist=True,
                        verbose=False,
                        imgsz=288,
                        tracker="bytetrack.yaml",
                    )
                self.last_results = results
            else:
                results = getattr(self, "last_results", None)

            # Thay vì dùng kết quả plot mặc định, chúng ta tự vẽ để kiểm soát hiển thị ID
            annotated_frame = frame.copy()

            if results and results[0].boxes and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy().astype(int)
                track_ids = results[0].boxes.id.int().cpu().numpy()

                for box, track_id in zip(boxes, track_ids):
                    x1, y1, x2, y2 = box

                    # Ưu tiên nhận diện trước khi quyết định hiển thị ID
                    is_known = (
                        track_id in self.track_history
                        and self.track_history[track_id] is not None
                    )

                    # Nếu chưa biết là ai, thử nhận diện (nhưng không thử quá nhiều lần để tránh lag)
                    if not is_known:
                        attempts = self.recognition_attempts.get(track_id, 0)

                        last_try = self.recognition_last_try.get(track_id, 0)
                        should_retry = (
                            loop_started - last_try >= RECOGNITION_RETRY_SECONDS
                        )

                        if attempts < MAX_RECOGNITION_ATTEMPTS and should_retry:
                            if track_id not in self.recognition_in_progress:
                                person_crop = frame[y1:y2, x1:x2].copy()
                                if person_crop.size > 0:
                                    self.recognition_in_progress.add(track_id)
                                    self.recognition_last_try[track_id] = loop_started
                                    # Chạy nhận diện trong thread riêng để không block stream
                                    threading.Thread(
                                        target=self._async_recognize,
                                        args=(person_crop, track_id, cam_obj, now),
                                        daemon=True,
                                    ).start()

                    # Hiển thị nhãn
                    if is_known:
                        val = self.track_history[track_id]
                        if val.startswith("Unknown_"):
                            # Đã đồng bộ ID người lạ từ GLOBAL_Unknown_REGISTRY
                            sid = val.split("_")[1]
                            label = f"Stranger {sid}"
                            color = (0, 0, 255)  # Đỏ cho người lạ
                        else:
                            # NGƯỜI QUEN: Chỉ hiển thị tên
                            label = val
                            color = (0, 255, 0)  # Xanh lá cho người quen
                    else:
                        # Đang trong quá trình nhận diện
                        attempts = self.recognition_attempts.get(track_id, 0)
                        if attempts < 5:
                            label = "Scanning..."
                            color = (255, 255, 0)  # Vàng
                        else:
                            # Trường hợp hi hữu không có face embedding nào ổn
                            label = f"Unknown {track_id}"
                            color = (0, 0, 255)

                        # Xử lý cảnh báo Telegram cho người lạ (vẫn giữ logic cũ)
                        if cam_obj.tracking_enabled:
                            count = self.unknown_counter.get(track_id, 0) + 1
                            self.unknown_counter[track_id] = count
                            if count == 30:
                                person_crop = frame[y1:y2, x1:x2]
                                if person_crop.size > 0:
                                    temp_path = f"tmp_unknown_{track_id}.jpg"
                                    cv2.imwrite(temp_path, person_crop)
                                    sendTelegramAlert(
                                        image_path=temp_path,
                                        alert_text=f"⚠ Người lạ (ID: {track_id}) tại camera {cam_obj.name}, lúc {now.strftime('%H:%M:%S %d/%m/%Y')}",
                                    )
                                    try:
                                        os.remove(temp_path)
                                    except:
                                        pass
                                    self.unknown_counter[track_id] = -9999

                    # Vẽ box và label lên frame
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(
                        annotated_frame,
                        label,
                        (x1, max(y1 - 10, 0)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.9,
                        color,
                        2,
                    )

            # Cập nhật luồng kết xuất cuối
            self.publish_frame(annotated_frame)
            time.sleep(
                max(0, (1 / TARGET_PROCESS_FPS) - (time.monotonic() - loop_started))
            )

        cap.release()


# Global Worker Manager
ACTIVE_CAM_WORKERS = {}


def start_camera(cam_id):
    # Nếu đã chạy, dừng trước để load cấu hình mới (attendance_enabled, v.v.)
    if cam_id in ACTIVE_CAM_WORKERS:
        stop_camera(cam_id)

    worker = CamWorker(cam_id)
    worker.start()
    ACTIVE_CAM_WORKERS[cam_id] = worker


def stop_camera(cam_id):
    if cam_id in ACTIVE_CAM_WORKERS:
        ACTIVE_CAM_WORKERS[cam_id].stop()
        del ACTIVE_CAM_WORKERS[cam_id]


def get_camera_frame(cam_id, with_meta=False):
    worker = ACTIVE_CAM_WORKERS.get(cam_id)
    if worker:
        frame_data = worker.get_frame()
        if frame_data:
            return frame_data if with_meta else frame_data[1]
    return (None, None, None) if with_meta else None
