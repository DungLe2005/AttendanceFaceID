from django.shortcuts import render, redirect
import os, unicodedata, re, cv2, base64, json
import numpy as np
from django.contrib.auth import login
from .models import Users
from facerecognition import FacialRecognition
from django.contrib import messages
from .models import *
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from facerecognition.utils import train

# Đường dẫn gốc
currentPythonFilePath = os.getcwd().replace("\\", "/")

# Tải model nhận diện 1 lần
face_detector = FacialRecognition.FaceDetector(
    minsize=20,
    threshold=[0.6, 0.7, 0.7],
    factor=0.709,
    gpu_memory_fraction=0.6,
    detect_face_model_path=os.path.join(currentPythonFilePath, "static/align"),
    facenet_model_path=os.path.join(
        currentPythonFilePath, "static/Models/20180402-114759.pb"
    ),
)

face_recognizer = FacialRecognition.FaceRecognition(
    classifier_path=os.path.join(currentPythonFilePath, "static/Models/facemodel.pkl")
)


# === Hàm chuẩn hóa tên file ===
def make_safe_filename(s):
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^0-9A-Za-z._-]+", "_", s)
    s = s.strip("_.-")
    return s or "user"


def register(request):
    if request.method == "POST":
        try:
            name = (request.POST.get("name") or "").strip()
            code = (request.POST.get("code") or "").strip()
            gender = request.POST.get("gender") or ""
            roll = request.POST.get("roll") or ""
            room = request.POST.get("class_name") or ""

            if not name or not code or not gender:
                return JsonResponse({"error": "Thiếu thông tin"}, status=400)

            if User.objects.filter(username=name).exists():
                return JsonResponse({"error": f"Tên '{name}' đã tồn tại"}, status=400)
            if Users.objects.filter(emcode=code).exists():
                return JsonResponse({"error": f"Mã '{code}' đã đăng ký"}, status=400)

            # Lấy danh sách ảnh
            images_json = request.POST.get("images")
            if not images_json:
                return JsonResponse({"error": "Không nhận được ảnh"}, status=400)

            images = json.loads(images_json)

            # Tạo thư mục user
            user_dir = os.path.join("static", "data", make_safe_filename(name))
            os.makedirs(user_dir, exist_ok=True)

            avatar_bytes = None
            avatar_name = None

            for i, item in enumerate(images):
                angle = item["angle"]
                img_data = item["image"]

                header, base64_data = img_data.split(",", 1)
                img_bytes = base64.b64decode(base64_data)

                # FILE NAME UNIQUE — không bao giờ ghi đè
                filename = f"{angle}_{i}.jpg"
                filepath = os.path.join(user_dir, filename)

                with open(filepath, "wb") as f:
                    f.write(img_bytes)

                if avatar_bytes is None:
                    avatar_bytes = img_bytes
                    avatar_name = f"{make_safe_filename(name)}.jpg"

            # Tạo user
            from django.core.files.base import ContentFile

            new_user = User.objects.create_user(
                username=make_safe_filename(name), password=code
            )
            user_detail = Users.objects.create(
                user=new_user,
                full=name,
                emcode=code,
                gender=gender,
                roll=roll,
                Class=room,
                created_at=timezone.now(),
            )

            if avatar_bytes:
                user_detail.face_image.save(
                    avatar_name, ContentFile(avatar_bytes), save=True
                )

            return JsonResponse({"success": True, "message": "Đăng ký thành công"})

        except Exception as e:
            print("Lỗi:", e)
            return JsonResponse(
                {"error": "Đã xảy ra lỗi trong quá trình đăng ký"}, status=500
            )

    return render(request, "register.html")


# --- Đăng nhập bằng khuôn mặt ---
def face_login(request):
    return render(request, "login.html")


def face_login_api(request):
    # login(request, User.objects.get(username='Le_Tuan_Dung'))  # Tạm thời đăng nhập luôn admin để test giao diện
    # return JsonResponse({
    #                 "success": True,
    #                 "message": "Đăng nhập thành công!",
    #                 "user": "admin"})
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "Chỉ hỗ trợ POST"})

    try:
        data = json.loads(request.body)
        img_data = data.get("image")

        if not img_data:
            return JsonResponse({"success": False, "message": "Thiếu dữ liệu ảnh"})

        # Tách base64
        img_str = img_data.split(",")[1]

        img_bytes = base64.b64decode(img_str)
        np_arr = np.frombuffer(img_bytes, np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Phát hiện khuôn mặt
        faces, _ = face_detector.get_faces(rgb)

        if faces is None or len(faces) == 0:
            return JsonResponse({"success": False, "message": "Không thấy khuôn mặt"})

        x1, y1, x2, y2 = faces[0][:4]
        face_img = rgb[int(y1) : int(y2), int(x1) : int(x2)]

        # Lấy embeddings
        embeddings = face_detector.get_embeddings(face_img)
        name, prob = face_recognizer.recognize_face(embeddings)

        if prob > 0.8:
            username = make_safe_filename(name)

            try:
                u = Users.objects.get(user__username=username, roll="Admin")
                login(request, u.user)

                return JsonResponse(
                    {
                        "success": True,
                        "message": "Đăng nhập thành công!",
                        "user": username,
                    }
                )

            except Users.DoesNotExist:
                return JsonResponse(
                    {"success": False, "message": "Khuôn mặt không có trong hệ thống"}
                )

        return JsonResponse({"success": False, "message": "Không nhận diện được"})

    except Exception as e:
        return JsonResponse({"success": False, "message": f"Lỗi: {str(e)}"})


@login_required
def home(request):
    user = request.user  # Lấy thông tin người đang đăng nhập
    return render(request, "home.html", {"user": user})
