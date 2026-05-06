import cv2
import mediapipe as mp
import numpy as np
import os
import time
import unicodedata, re
import threading

# === Hàm chuẩn hóa tên file ===
def make_safe_filename(s):
    s = unicodedata.normalize('NFKD', s)
    s = s.encode('ascii', 'ignore').decode('ascii')
    s = re.sub(r'[^0-9A-Za-z._-]+', '_', s)
    s = s.strip('_.-')
    return s or 'user'

# === Hàm chuẩn hóa landmarks thành vector feature ===
def get_normalized_vector(face_landmarks):
    all_points = np.array([[lm.x, lm.y] for lm in face_landmarks.landmark])
    center = np.mean(all_points, axis=0)
    scale = np.linalg.norm(all_points.max(axis=0) - all_points.min(axis=0))
    normalized_points = (all_points - center) / scale
    left_eye = np.mean(normalized_points[33:133], axis=0)
    right_eye = np.mean(normalized_points[362:462], axis=0)
    nose = normalized_points[1]
    mouth = np.mean(normalized_points[61:291], axis=0)
    forehead = np.mean(normalized_points[[10,151,9,338]], axis=0)
    feature_vec = np.concatenate([left_eye, right_eye, nose, mouth, forehead, [scale]])
    return feature_vec

# class FaceCaptureThread:
#     def __init__(self, name):
#         self.name = name
#         self.safe_name = make_safe_filename(name)
#         self.save_dir = os.path.join("static", "data", self.safe_name)
#         os.makedirs(self.save_dir, exist_ok=True)

#         self.cap = cv2.VideoCapture(0)
#         self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
#         self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

#         self.mp_face_mesh = mp.solutions.face_mesh
#         self.face_mesh = self.mp_face_mesh.FaceMesh(refine_landmarks=True, min_detection_confidence=0.5)

#         # Biến trạng thái chia sẻ cho Django
#         self.current_angle = None
#         self.current_instruction = "Đang khởi động camera..."
#         self.total_progress = 0
#         self.finished = False
#         self.running = True
#         self.lock = threading.Lock()

#         # Thread chạy ngầm
#         self.thread = threading.Thread(target=self.run, daemon=True)
#         self.thread.start()

#     def run(self):
#         angle_names = ["center", "center_far", "right_slight", "right",
#                     "left_slight", "left", "up", "down"]
#         angle_needed = {
#             "center": 3, "center_far": 1, "right_slight": 1, "right": 1,
#             "left_slight": 1, "left": 1, "up": 1, "down": 1
#         }
#         angle_counts = {name: 0 for name in angle_names}

#         text_map = {
#             "center": "Giữ mặt thẳng",
#             "center_far": "Lùi xa camera",
#             "right_slight": "Quay phải nhẹ",
#             "right": "Quay phải",
#             "left_slight": "Quay trái nhẹ",
#             "left": "Quay trái",
#             "up": "Ngẩng mặt lên",
#             "down": "Cúi mặt xuống"
#         }

#         # Vector đặc trưng chuẩn
#         angle_vectors = {
#             "center": np.array([-0.107, -0.0146, 0.111, 0.0393, 0.005, 0.055, -0.063, 0.0025, 0.03, -0.39, 0.75]),
#             "center_far": np.array([-0.1052, -0.0222, 0.111, 0.0481, -0.0023, 0.0419, -0.0629, -0.0013, 0.0376, -0.3811, 0.4913]),
#             "right_slight": np.array([-0.0987, -0.0155, 0.1018, 0.038, 0.0529, 0.0547, -0.0609, 0.0028, 0.053, -0.3795, 0.6524]),
#             "right": np.array([-0.0644, -0.0304, 0.0649, 0.0501, 0.1111, 0.031, -0.043, -0.0028, 0.0486, -0.3613, 0.6842]),
#             "left_slight": np.array([-0.1043, -0.0139, 0.1122, 0.0419, -0.0497, 0.0412, -0.0585, 0.0016, -0.0036, -0.3848, 0.63]),
#             "left": np.array([-0.0894, -0.0117, 0.0988, 0.0422, -0.0864, 0.0278, -0.0490, 0.0025, -0.0182, -0.3859, 0.6336]),
#             "up": np.array([-0.105, -0.0176, 0.1119, 0.0427, 0.0037, 0.0065, -0.0622, 0.0039, 0.021, -0.3846, 0.6845]),
#             "down": np.array([-0.1113, -0.0175, 0.1162, 0.042, -0.0053, 0.0854, -0.0656, -0.0008, 0.0368, -0.3782, 0.5582])
#         }

#         stable_duration = 1.0
#         stable_start = None
#         landmark_buffer = []

#         # Vị trí trung tâm giả định (dùng cho kiểm tra lệch)
#         center_tolerance = (0.15, 0.2)  # sai lệch cho phép

#         while self.running:
#             ret, frame = self.cap.read()
#             if not ret:
#                 continue

#             frame = cv2.flip(frame, 1)
#             clean_frame = frame.copy()
#             h, w, _ = frame.shape

#             # kiểm tra còn góc nào cần chụp không
#             remaining = [a for a in angle_names if angle_counts[a] < angle_needed[a]]
#             if not remaining:
#                 with self.lock:
#                     self.finished = True
#                     self.current_instruction = "Đã hoàn thành đăng ký khuôn mặt!"
#                     self.total_progress = 100
#                 break

#             next_angle = remaining[0]
#             with self.lock:
#                 self.current_angle = next_angle
#                 self.current_instruction = text_map[next_angle]
#                 self.total_progress = round(
#                     (sum(angle_counts.values()) / sum(angle_needed.values())) * 100, 1
#                 )

#             # Xử lý bằng MediaPipe
#             rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
#             results = self.face_mesh.process(rgb)

#             if results.multi_face_landmarks:
#                 face_landmarks = results.multi_face_landmarks[0]
#                 feature_vec = get_normalized_vector(face_landmarks)

#                 # kiểm tra độ ổn định
#                 landmark_buffer.append(feature_vec)
#                 if len(landmark_buffer) > 5:
#                     landmark_buffer.pop(0)
#                 avg_vec = np.mean(landmark_buffer, axis=0)
#                 dist = np.linalg.norm(avg_vec - angle_vectors[next_angle])

#                 if dist < 0.1:
#                     if stable_start is None:
#                         stable_start = time.time()
#                     elif time.time() - stable_start >= stable_duration:
#                         angle_counts[next_angle] += 1
#                         filename = os.path.join(self.save_dir, f"{next_angle}_{angle_counts[next_angle]}.jpg")
#                         cv2.imwrite(filename, clean_frame)
#                         stable_start = None
#                         landmark_buffer = []
#                 else:
#                     stable_start = None
#             else:
#                 stable_start = None

#             # nghỉ nhẹ để tránh quá tải CPU
#             time.sleep(0.02)

#         # Kết thúc
#         self.cap.release()
#         self.face_mesh.close()
#         with self.lock:
#             self.running = False
#             self.finished = True
#         print(f"[INFO] Face capture hoàn tất cho {self.name}")


#     def get_status(self):
#         """Hàm an toàn để Django đọc hướng dẫn hiện tại"""
#         with self.lock:
#             return {
#                 "angle": self.current_angle,
#                 "instruction": self.current_instruction,
#                 "progress": self.total_progress,
#                 "finished": self.finished
#             }

#     def stop(self):
#         self.running = False