from django.shortcuts import get_object_or_404, redirect
from django.shortcuts import render, redirect
from .models import *
from Auth_app.models import Users
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse, HttpResponse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.db.models import F
from facerecognition import FacialRecognition
from django.utils import timezone as TZ
from Auth_app.views import make_safe_filename
from datetime import time as TimeP, datetime, timedelta
from .utils import sendTelegramAlert, send_command_to_esp32
from .workers import update_devices_status
from django.core.paginator import Paginator
import pandas as pd
import io


import os
import json
import shutil
import stat
from facerecognition.utils import *
import base64
import numpy as np
import time as t
import re


# Khởi tạo module nhận diện
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


def load(request):
    return render(request, "loading.html")


# update_devices_status moved to workers.py


def manager_User(request):
    # Lấy dữ liệu từ thanh lọc
    name_query = request.GET.get("name", "")
    code_query = request.GET.get("code", "")
    roll_query = request.GET.get("roll", "")

    # Query mặc định
    users = Users.objects.all()

    # Nếu có lọc tên
    if name_query:
        users = users.filter(full__icontains=name_query)

    # Nếu có lọc mã số
    if code_query:
        users = users.filter(emcode__icontains=code_query)

    # Nếu có lọc vai trò
    if roll_query:
        users = users.filter(roll=roll_query)

    users = users.order_by("id")

    # --- Phân trang ---
    paginator = Paginator(users, 10)  # 10 người/trang
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "users": users,
        "name_query": name_query,
        "code_query": code_query,
        "page_obj": page_obj,
        "total": users.count(),
    }

    return render(request, "ad_manager_user.html", context)


def updatePermission(request, id):
    user = get_object_or_404(Users, pk=id)
    if request.method == "POST":
        user.roll = "Admin"
        user.save()
        messages.success(request, f"Cập nhật quyền cho {user.full} thành công.")
        return redirect("manager_users")


@csrf_exempt
def cam_page(request, cam_label):
    return render(request, "cam_page.html", {"camera_label": cam_label})


# Đếm số frame bị nghi ngờ unknown theo ID
unknown_counter = {}
known_unknowns_cache = {}


@csrf_exempt
def track_post_in(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    camera_label = request.POST.get("camera", "CAM")
    camera_id = request.POST.get("camera_id")
    frame_data = request.POST.get("frame")
    if not frame_data:
        return JsonResponse({"ok": False, "error": "No frame"}, status=400)

    # Xác định chế độ bật/tắt cho camera này
    do_attendance = True
    do_tracking = True
    if camera_id:
        try:
            cam_obj = IPCamera.objects.get(pk=camera_id)
            do_attendance = cam_obj.attendance_enabled
            do_tracking = cam_obj.tracking_enabled
        except IPCamera.DoesNotExist:
            pass

    if "," in frame_data:
        frame_data = frame_data.split(",")[1]
    img_bytes = base64.b64decode(frame_data)
    nparr = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return JsonResponse(
            {"ok": False, "error": "Failed to decode image"}, status=400
        )

    people_detected = []
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces, _ = detector.get_faces(rgb)

    now = TZ.localtime(TZ.now())
    today = now.date()
    response_msg = None

    for face in faces:
        x1, y1, x2, y2 = list(map(int, face[:4]))
        face_img = rgb[y1:y2, x1:x2]
        if face_img.size == 0:
            continue

        embeddings = detector.get_embeddings(face_img).reshape(1, -1)
        username, prob = recognizer.recognize_face(embeddings)

        if username and prob >= 0.7:
            # === Người quen ===
            user_obj = Users.objects.filter(
                user__username=make_safe_filename(username)
            ).first()

            if user_obj and do_attendance:
                # print(f"[Frontend] Nhận diện: {username} (prob: {prob:.2f}), Vai trò: {user_obj.roll}")
                if user_obj.roll == "Student":
                    schedule = CalendarEvent.objects.filter(
                        date=today,
                        Class=user_obj.Class,
                        start_time__lte=now.time(),
                        end_time__gte=now.time(),
                    ).first()

                    # print("Schedule found:", schedule)
                    # print(f"[Frontend] Tìm thấy lịch học: {schedule.title} cho {username}")
                    # Nếu có môn học trong giờ hiện tại
                    if schedule:
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

                        if not created:
                            response_msg = f"Đã điểm danh sinh viên: {user_obj.full}"
                        else:
                            response_msg = f"Điểm danh VÀO thành công cho sinh viên: {user_obj.full}"

                        update_devices_status(schedule.room, "on")

                        TimeOffDevice.objects.update_or_create(
                            room=schedule.room, defaults={"time": schedule.end_time}
                        )

                    else:
                        print(f"[Frontend] Không tìm thấy lịch học cho lớp {user_obj.Class} lúc {now.time()}")
                        response_msg = (
                            f"Hôm nay không có lịch học cho lớp {user_obj.Class}."
                        )

                # === Giáo viên ===
                elif user_obj.roll in ["Teacher", "Admin"]:
                    shift = "Sáng" if now.hour < 12 else "Chiều"
                    timeoff_auto = (now + timedelta(hours=4, minutes=30)).time()

                    attendance_qs = Attendance.objects.filter(
                        emcode=user_obj.emcode, date=today, shift=shift
                    )

                    if attendance_qs.exists():
                        attendance = attendance_qs.first()

                        if attendance.checkin:
                            response_msg = f"Giáo viên/Nhân viên {user_obj.full} đã điểm danh trước đó."
                            people_detected.append(
                                {
                                    "type": "known",
                                    "name": username,
                                    "bbox": [x1, y1, x2, y2],
                                }
                            )
                            continue
                        else:
                            attendance.checkin = now.time()
                            attendance.save()

                    else:
                        Attendance.objects.create(
                            emcode=user_obj.emcode,
                            name=user_obj.full,
                            date=today,
                            shift=shift,
                            checkin=now.time(),
                        )

                    update_devices_status(user_obj.Class, "on")

                    TimeOffDevice.objects.update_or_create(
                        room=user_obj.Class, defaults={"time": timeoff_auto}
                    )

            people_detected.append(
                {"type": "known", "name": username, "bbox": [x1, y1, x2, y2]}
            )
        else:
            # === Người lạ — chỉ xử lý nếu tracking bật ===
            if not do_tracking:
                people_detected.append({"type": "unknown", "bbox": [x1, y1, x2, y2]})
                continue

            face_id = f"{x1}_{y1}_{x2}_{y2}"
            embedding_tuple = tuple(embeddings.flatten())

            if (
                face_id in known_unknowns_cache
                and known_unknowns_cache[face_id] == "known"
            ):
                people_detected.append(
                    {"type": "known", "name": username, "bbox": [x1, y1, x2, y2]}
                )
                continue

            count = unknown_counter.get(face_id, 0) + 1
            unknown_counter[face_id] = count

            if count >= 3:
                embeddings2 = detector.get_embeddings(face_img).reshape(1, -1)
                username2, prob2 = recognizer.recognize_face(embeddings2)

                if not (username2 and prob2 >= 0.7):
                    temp_path = f"tmp_{face_id}.jpg"
                    cv2.imwrite(temp_path, cv2.cvtColor(face_img, cv2.COLOR_RGB2BGR))

                    sendTelegramAlert(
                        image_path=temp_path,
                        alert_text=f"⚠ Người lạ tại {camera_label}, {now}",
                    )

                    os.remove(temp_path)
                    known_unknowns_cache[face_id] = "alerted"

                else:
                    known_unknowns_cache[face_id] = "known"
                    people_detected.append(
                        {"type": "known", "name": username2, "bbox": [x1, y1, x2, y2]}
                    )
                    continue

            people_detected.append(
                {"type": "unknown", "bbox": [x1, y1, x2, y2], "count": count}
            )

    return JsonResponse(
        {"ok": True, "people": people_detected, "message": response_msg}
    )


@csrf_exempt
def track_post_out(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "POST only"}, status=405)

    camera_id = request.POST.get("camera_id")
    frame_data = request.POST.get("frame")
    if not frame_data:
        return JsonResponse({"ok": False, "error": "No frame"}, status=400)

    # Kiểm tra chế độ attendance cho camera này
    do_attendance = True
    if camera_id:
        try:
            cam_obj = IPCamera.objects.get(pk=camera_id)
            do_attendance = cam_obj.attendance_enabled
        except IPCamera.DoesNotExist:
            pass

    now = TZ.localtime(TZ.now())
    today = now.date()
    response_msg = None

    # decode base64
    if "," in frame_data:
        frame_data = frame_data.split(",")[1]
    img_bytes = base64.b64decode(frame_data)
    nparr = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if frame is None:
        return JsonResponse(
            {"ok": False, "error": "Failed to decode image"}, status=400
        )

    people_detected = []

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces, _ = detector.get_faces(rgb)

    for face in faces:
        x1, y1, x2, y2 = face[:4]
        face_img = rgb[int(y1) : int(y2), int(x1) : int(x2)]
        if face_img.size == 0:
            continue

        embeddings = detector.get_embeddings(face_img).reshape(1, -1)
        username, prob = recognizer.recognize_face(embeddings)

        if username and prob >= 0.8:
            user_obj = Users.objects.filter(
                user__username=make_safe_filename(username)
            ).first()
            if user_obj and do_attendance:
                if user_obj.roll == "Student":
                    schedule = CalendarEvent.objects.filter(
                        date=today, Class=user_obj.Class, end_time__lte=now.time()
                    ).last()
                    if schedule:
                        attendance_qs = Attendance.objects.filter(
                            emcode=user_obj.emcode, date=today, subject=schedule.title
                        )
                        if attendance_qs.exists():
                            attendance = attendance_qs.filter(
                                checkout__isnull=True
                            ).first()
                            if attendance:
                                attendance.checkout = now.time()
                                attendance.save()
                                response_msg = (
                                    f"Sinh viên {user_obj.full} đã điểm danh ra."
                                )
                        else:
                            people_detected.append(
                                {
                                    "type": "known",
                                    "name": username,
                                    "bbox": [x1, y1, x2, y2],
                                }
                            )
                            continue

                elif user_obj.roll in ["Teacher", "Admin"]:
                    shift = "Sáng" if now.hour < 12 else "Chiều"
                    attendance_qs = Attendance.objects.filter(
                        emcode=user_obj.emcode, date=today, shift=shift
                    )
                    if attendance_qs.exists():
                        attendance = attendance_qs.first()
                        if attendance.checkout is not None:
                            people_detected.append(
                                {
                                    "type": "known",
                                    "name": username,
                                    "bbox": [x1, y1, x2, y2],
                                }
                            )
                            continue
                        else:
                            attendance.checkout = now.time()
                            attendance.save()
                            response_msg = (
                                f"Giáo viên/Nhân viên {user_obj.full} đã điểm danh ra."
                            )
            people_detected.append(
                {"type": "known", "name": username, "bbox": [x1, y1, x2, y2]}
            )

    return JsonResponse(
        {"ok": True, "people": people_detected, "message": response_msg}
    )


def attendance_page(request):
    now = TZ.localtime(TZ.now())
    today = now.date()

    # --- Lọc Sinh viên ---
    s_date_str = request.GET.get("s_date")
    s_name = request.GET.get("s_name", "")
    s_code = request.GET.get("s_code", "")
    s_subject = request.GET.get("s_subject", "")

    student_attendance = Attendance.objects.filter(subject__isnull=False)

    s_date_obj = today
    if s_date_str:
        try:
            s_date_obj = datetime.strptime(s_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    student_attendance = student_attendance.filter(date=s_date_obj)
    if s_name:
        student_attendance = student_attendance.filter(name__icontains=s_name)
    if s_code:
        student_attendance = student_attendance.filter(emcode__icontains=s_code)
    if s_subject:
        student_attendance = student_attendance.filter(subject__icontains=s_subject)

    # --- Lọc Giáo viên ---
    t_date_str = request.GET.get("t_date")
    t_name = request.GET.get("t_name", "")
    t_shift = request.GET.get("t_shift", "")

    teacher_attendance = Attendance.objects.filter(shift__isnull=False)

    t_date_obj = today
    if t_date_str:
        try:
            t_date_obj = datetime.strptime(t_date_str, "%Y-%m-%d").date()
        except ValueError:
            pass

    teacher_attendance = teacher_attendance.filter(date=t_date_obj)
    if t_name:
        teacher_attendance = teacher_attendance.filter(name__icontains=t_name)
    if t_shift:
        teacher_attendance = teacher_attendance.filter(shift__icontains=t_shift)

    return render(
        request,
        "ad_attendance.html",
        {
            "student_attendance": student_attendance,
            "teacher_attendance": teacher_attendance,
            "s_date": s_date_str or str(today),
            "t_date": t_date_str or str(today),
        },
    )


def export_attendance(request):
    filter_type = request.GET.get("filter")

    if filter_type == "student":
        date_filter = request.GET.get("s_date")
        name_filter = request.GET.get("s_name", "")
        code_filter = request.GET.get("s_code", "")
        subject_filter = request.GET.get("s_subject", "")
        queryset = Attendance.objects.filter(subject__isnull=False)
        filename_prefix = "Attendance_Student"
    else:
        date_filter = request.GET.get("t_date")
        name_filter = request.GET.get("t_name", "")
        shift_filter = request.GET.get("t_shift", "")
        queryset = Attendance.objects.filter(shift__isnull=False)
        filename_prefix = "Attendance_Teacher_Staff"

    if date_filter:
        try:
            target_date = datetime.strptime(date_filter, "%Y-%m-%d").date()
            queryset = queryset.filter(date=target_date)
        except ValueError:
            pass

    if name_filter:
        queryset = queryset.filter(name__icontains=name_filter)

    if filter_type == "student" and code_filter:
        queryset = queryset.filter(emcode__icontains=code_filter)

    if filter_type == "student" and subject_filter:
        queryset = queryset.filter(subject__icontains=subject_filter)

    if filter_type == "teacher" and shift_filter:
        queryset = queryset.filter(shift__icontains=shift_filter)

    queryset = queryset.order_by("-date", "name")

    # Convert to DataFrame
    data = []
    for a in queryset:
        row = {
            "Ngày": a.date.strftime("%d/%m/%Y"),
            "Mã số": a.emcode,
            "Tên": a.name,
        }
        if filter_type == "student":
            row["Môn học"] = a.subject
        else:
            row["Ca làm việc"] = a.shift

        row["Giờ Vào"] = a.checkin.strftime("%H:%M:%S") if a.checkin else "--:--:--"
        row["Giờ Ra"] = a.checkout.strftime("%H:%M:%S") if a.checkout else "--:--:--"
        data.append(row)

    if not data:
        messages.warning(request, "Không có dữ liệu để xuất báo cáo.")
        return redirect("ad_attendance")

    df = pd.DataFrame(data)

    # Create Excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")

    output.seek(0)

    filename = f"{filename_prefix}_{date_filter or 'All'}.xlsx"
    response = HttpResponse(
        output,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f"attachment; filename={filename}"

    return response


def delete_Attendence(request, id):
    attendance = get_object_or_404(Attendance, pk=id)
    attendance.delete()
    messages.success(request, "Xóa bản ghi điểm danh thành công!")
    return redirect("ad_attendance")

def remove_readonly(func, path, excinfo):
    """
    Error handler for shutil.rmtree to handle read-only files on Windows.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


def delete_user(request, id):
    # id la khoa chinh cua model Users
    user_detail = get_object_or_404(Users, pk=id)
    user = user_detail.user
    emcode = user_detail.emcode

    try:
        # 1. Xoa thu muc anh training
        safe_username = make_safe_filename(user.username)
        user_data_dir = os.path.join(settings.BASE_DIR, "static", "data", safe_username)
        if os.path.exists(user_data_dir):
            shutil.rmtree(user_data_dir, onerror=remove_readonly)

        # 2. Xoa du lieu xu ly
        raw_data_dir = os.path.join(settings.BASE_DIR, "static", "data_process", "raw", safe_username)
        processed_data_dir = os.path.join(settings.BASE_DIR, "static", "data_process", "process", safe_username)
        for d in [raw_data_dir, processed_data_dir]:
            if os.path.exists(d):
                shutil.rmtree(d, onerror=remove_readonly)

        # 3. Xoa anh khuon mat
        if user_detail.face_image:
            try:
                if os.path.exists(user_detail.face_image.path):
                    os.remove(user_detail.face_image.path)
            except Exception as e:
                print(f"Error deleting face image: {e}")

        # 4. Xoa diem danh
        Attendance.objects.filter(emcode=emcode).delete()
        user_detail.delete()

    except Exception as e:
        print(f"Error in delete_user cleanup: {e}")

    # 5. Xoa tai khoan
    user.delete()
    messages.success(request, "Đã xóa người dùng và toàn bộ dữ liệu liên quan thành công.")
    return redirect("manager_users")



@login_required
def schedule_Page(request):
    title = request.GET.get("search", "").strip()
    if title:
        tags = Tag.objects.filter(title__icontains=title)
    else:
        tags = Tag.objects.all()
    events = CalendarEvent.objects.all()
    # Lấy danh sách các phòng từ Device model
    rooms = Device.objects.values_list("room", flat=True).distinct()
    return render(
        request, "ad_manager_schedule.html", {"tags": tags, "events": events, "rooms": rooms}
    )


@login_required
def save_Tag(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            title = data.get("title", "").strip()
            if not title:
                return JsonResponse(
                    {"status": "error", "message": "Tên buổi học không được để trống"}
                )

            tag = Tag.objects.create(
                title=title,
                classname=data.get("classname", "").strip(),
                start_time=data.get("start_time"),
                end_time=data.get("end_time"),
                room=data.get("room", "").strip(),
                teacher=data.get("teacher", "").strip(),
            )
            return JsonResponse(
                {"status": "success", "message": "Thêm thẻ thành công", "id": tag.id}
            )
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})


@login_required
def edit_Tag(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": True, "message": "Dữ liệu không hợp lệ"})

        tag_id = data.get("id")
        tag = get_object_or_404(Tag, pk=tag_id)

        tag.title = data.get("title", tag.title)
        tag.classname = data.get("classname", tag.classname)
        tag.start_time = data.get("start_time", tag.start_time)
        tag.end_time = data.get("end_time", tag.end_time)
        tag.room = data.get("room", tag.room)
        tag.teacher = data.get("teacher", tag.teacher)

        tag.save()
        return JsonResponse({"error": False, "message": "Cập nhật thẻ thành công"})

    return JsonResponse({"error": True, "message": "Phương thức không hợp lệ"})


@login_required
def delete_Tag(request, id):
    tag = get_object_or_404(Tag, pk=id)
    tag.delete()
    return JsonResponse({"success": True, "message": "Xóa thẻ thành công"})


def parse_time(t: str):
    try:
        return datetime.strptime(t, "%H:%M").time()
    except ValueError:
        return None


@login_required
def save_Event(request):
    if request.method != "POST":
        return JsonResponse({"error": "Phương thức không hợp lệ"}, status=405)

    try:
        data = json.loads(request.body.decode("utf-8"))

        title = data.get("title", "Không tên")
        date_str = data.get("date", "")
        start_str = data.get("start_time")
        end_str = data.get("end_time")
        room = data.get("room", "")
        teacher = data.get("teacher", "")
        classname = data.get("classname", "")

        if not date_str or not start_str or not end_str:
            return JsonResponse(
                {"error": "Dữ liệu ngày hoặc giờ không hợp lệ"}, status=400
            )

        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_time = parse_time(start_str)
        end_time = parse_time(end_str)
        event = CalendarEvent.objects.create(
            title=title,
            date=date_obj,
            start_time=start_time,
            end_time=end_time,
            room=room,
            teacher=teacher,
            Class=classname,
        )

        return JsonResponse(
            {"error": False, "message": f"Sự kiện {title} đã lưu", "id": event.id}
        )

    except Exception as e:
        print("SAVE EVENT ERROR:", e)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def edit_Event(request):
    if request.method == "POST":
        try:
            # Hỗ trợ cả JSON body (cho kéo thả) và POST form (cho modal nếu có)
            if request.content_type == "application/json":
                data = json.loads(request.body)
            else:
                data = request.POST

            id = data.get("id")
            event = get_object_or_404(CalendarEvent, pk=id)

            if "title" in data:
                event.title = data.get("title")
            if "date" in data:
                event.date = datetime.strptime(data.get("date"), "%Y-%m-%d").date()
            if "start_time" in data:
                event.start_time = parse_time(data.get("start_time"))
            if "end_time" in data:
                event.end_time = parse_time(data.get("end_time"))
            if "room" in data:
                event.room = data.get("room")
            if "teacher" in data:
                event.teacher = data.get("teacher")
            if "classname" in data:
                event.Class = data.get("classname")

            event.save()
            return JsonResponse(
                {"success": True, "message": "Cập nhật lịch thành công"}
            )
        except Exception as e:
            return JsonResponse({"success": False, "message": str(e)}, status=500)

    return JsonResponse({"success": False, "message": "Invalid method"})


@login_required
def delete_Event(request, id):
    event = get_object_or_404(CalendarEvent, pk=id)
    event.delete()
    return JsonResponse({"success": True, "message": "Xóa sự kiện thành công"})


def get_events(request):
    try:
        events = CalendarEvent.objects.all()
        data = []

        for e in events:
            date_str = e.date.strftime("%Y-%m-%d")

            start_iso = f"{date_str}T{e.start_time.strftime('%H:%M:%S')}"
            end_iso = f"{date_str}T{e.end_time.strftime('%H:%M:%S')}"

            data.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "start": start_iso,
                    "end": end_iso,
                    "extendedProps": {
                        "start": start_iso,
                        "end": end_iso,
                        "room": e.room,
                        "teacher": e.teacher,
                        "Class": e.Class,
                    },
                }
            )

        print("=== EVENT DATA SENT ===")
        print(data)

        return JsonResponse(data, safe=False)
    except Exception as e:
        print("GET EVENTS ERROR:", e)
        return JsonResponse({"error": str(e)}, status=500)


def Logout(request):
    logout(request)
    return redirect("face_login")


def admin_home(request):
    # if not request.user.is_authenticated:
    #     return redirect('ad_login')
    return render(request, "admin_home.html")


def ad_train(request):
    notify = request.GET.get("notify", None)
    if notify == "1":
        messages.success(request, "Bạn vừa xóa tài khoản cần train dữ liệu lại.")

    return render(request, "ad_train.html")


# --- QUẢN LÝ IP CAMERA & STREAMING ---
# --- QUẢN LÝ IP CAMERA & STREAMING ---
from facerecognition.tracker import (
    start_camera,
    stop_camera,
    get_camera_frame,
    HTTPVideoCapture,
    ACTIVE_CAM_WORKERS,
)


def manager_cam(request):
    cams = IPCamera.objects.all()
    # Tự động refresh worker khi load trang này để đảm bảo trạng thái các cam
    for cam in cams:
        if cam.status:
            if cam.id not in ACTIVE_CAM_WORKERS:
                start_camera(cam.id)
        else:
            if cam.id in ACTIVE_CAM_WORKERS:
                stop_camera(cam.id)

    return render(request, "ad_manager_cam.html", {"cams": cams})


def add_cam(request):
    if request.method == "POST":
        name = request.POST.get("name")
        ip_address = request.POST.get("ip_address")
        cam_type = request.POST.get("cam_type")
        status = request.POST.get("status") == "on"
        attendance_enabled = request.POST.get("attendance_enabled") == "on"
        tracking_enabled = request.POST.get("tracking_enabled") == "on"

        cam = IPCamera.objects.create(
            name=name,
            ip_address=ip_address,
            cam_type=cam_type,
            status=status,
            attendance_enabled=attendance_enabled,
            tracking_enabled=tracking_enabled,
        )
        if status:
            start_camera(cam.id)
        messages.success(request, "Thêm camera thành công!")
        return redirect("manager_cam")
    return redirect("manager_cam")


def edit_cam(request, cam_id):
    cam = get_object_or_404(IPCamera, pk=cam_id)
    if request.method == "POST":
        cam.name = request.POST.get("name")
        cam.ip_address = request.POST.get("ip_address")
        cam.cam_type = request.POST.get("cam_type")
        new_status = request.POST.get("status") == "on"
        cam.attendance_enabled = request.POST.get("attendance_enabled") == "on"
        cam.tracking_enabled = request.POST.get("tracking_enabled") == "on"

        cam.status = new_status
        cam.save()

        if new_status:
            start_camera(cam.id)
        else:
            stop_camera(cam.id)

        messages.success(request, "Cập nhật camera thành công!")
        return redirect("manager_cam")
    return redirect("manager_cam")


def delete_cam(request, cam_id):
    cam = get_object_or_404(IPCamera, pk=cam_id)
    stop_camera(cam.id)  # Dừng worker nếu đang chạy
    cam.delete()
    messages.success(request, "Xóa camera thành công!")
    return redirect("manager_cam")


@csrf_exempt
def toggle_cam_feature(request, cam_id):
    """API bật/tắt attendance_enabled hoặc tracking_enabled cho camera."""
    if request.method != "POST":
        return JsonResponse({"ok": False}, status=405)
    cam = get_object_or_404(IPCamera, pk=cam_id)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

    field = data.get("field")  # "attendance_enabled" hoặc "tracking_enabled"
    value = data.get("value")  # True hoặc False

    if field == "attendance_enabled":
        cam.attendance_enabled = bool(value)
    elif field == "tracking_enabled":
        cam.tracking_enabled = bool(value)
    else:
        return JsonResponse({"ok": False, "error": "Invalid field"}, status=400)

    cam.save()
    return JsonResponse({"ok": True, "field": field, "value": bool(value)})


# --- DASHBOARD THIẾT BỊ ---
@login_required
def device_dashboard(request):
    """Trang Dashboard hiển thị trạng thái thiết bị theo phòng."""
    rooms = Device.objects.values_list("room", flat=True).distinct()
    return render(request, "ad_device_dashboard.html", {"rooms": rooms})


def api_device_status(request):
    """API trả về trạng thái tất cả thiết bị (cho JS polling và Dashboard)."""
    devices = Device.objects.all()
    now = TZ.localtime().time()

    # Tự động tắt thiết bị nếu đã hết giờ (logic này cũng được thực hiện bởi worker chạy ngầm)
    for toff in TimeOffDevice.objects.all():
        if toff.time and toff.time <= now:
            update_devices_status(toff.room, "off")
            toff.delete()

    data = []
    for d in devices:
        data.append(
            {
                "id": d.id,
                "name": d.name,
                "room": d.room,
                "status": d.status,
                "ip_address": d.ip_address,
            }
        )
    return JsonResponse({"devices": data})


# --- API GIAO TIẾP ESP32 ---
@csrf_exempt
def api_device_sync(request):
    """
    Endpoint /api/device/sync/ cho ESP32 polling.
    GET  → Trả về trạng thái Quạt và LED từ DB.
    POST → ESP32 xác nhận đã thực hiện lệnh, cập nhật DB.
    """
    if request.method == "GET":
        room = request.GET.get("room", "1")
        devices = Device.objects.filter(room=room)

        fan_status = "off"
        led_status = "off"
        for d in devices:
            name_lower = d.name.lower()
            if "quạt" in name_lower or "quat" in name_lower or "fan" in name_lower:
                fan_status = d.status
            elif "led" in name_lower or "đèn" in name_lower or "den" in name_lower:
                led_status = d.status

        return JsonResponse(
            {
                "fan": fan_status,
                "led": led_status,
                "room": room,
            }
        )

    elif request.method == "POST":
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        room = data.get("room", "1")
        fan_confirmed = data.get("fan")
        led_confirmed = data.get("led")

        if fan_confirmed is not None:
            Device.objects.filter(room=room, name__icontains="quạt").update(
                status=fan_confirmed
            )
            Device.objects.filter(room=room, name__icontains="fan").update(
                status=fan_confirmed
            )

        if led_confirmed is not None:
            Device.objects.filter(room=room, name__icontains="led").update(
                status=led_confirmed
            )
            Device.objects.filter(room=room, name__icontains="đèn").update(
                status=led_confirmed
            )

        return JsonResponse({"ok": True, "message": "Cập nhật trạng thái thành công"})

    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


def stream_cam(request, cam_id):
    def gen_frame(cid):
        import time

        last_seq = -1
        while True:
            seq, frame, _ = get_camera_frame(cid, with_meta=True)
            if frame and seq != last_seq:
                last_seq = seq
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Content-Length: " + str(len(frame)).encode("ascii") + b"\r\n\r\n"
                    + frame
                    + b"\r\n\r\n"
                )
            else:
                time.sleep(0.03 if frame else 0.15)

    return StreamingHttpResponse(
        gen_frame(cam_id), content_type="multipart/x-mixed-replace; boundary=frame"
    )


@csrf_exempt
def add_device(request):
    if request.method == "POST":
        try:
            name = request.POST.get("name")
            room = request.POST.get("room")
            ip_address = request.POST.get("ip_address")
            if not name or not room:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": f"Missing data: name='{name}', room='{room}'",
                    },
                    status=400,
                )
            device = Device.objects.create(name=name, room=room, ip_address=ip_address)
            return JsonResponse({"ok": True, "id": device.id})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)
    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def delete_device(request, device_id):
    if request.method == "POST":
        device = Device.objects.get(id=device_id)
        device.delete()
        return JsonResponse({"ok": True})
    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def toggle_device(request, device_id):
    if request.method == "POST":
        try:
            device = Device.objects.get(id=device_id)
            device.status = "on" if device.status == "off" else "off"
            device.save()

            # Gửi lệnh trực tiếp tới ESP32 (Push Model)
            send_command_to_esp32(device.ip_address, device.name, device.status)

            return JsonResponse({"ok": True, "status": device.status})
        except Device.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Device not found"}, status=404)
    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)


@csrf_exempt
def update_device_ip(request, device_id):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            ip = data.get("ip_address")
            device = Device.objects.get(id=device_id)
            device.ip_address = ip
            device.save()
            return JsonResponse({"ok": True})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)
    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
@csrf_exempt
def toggle_room_devices(request, room):
    """API bật/tắt toàn bộ thiết bị trong một phòng."""
    if request.method == "POST":
        try:
            # Mặc định là tắt (off) nếu không truyền status
            status = request.POST.get("status", "off")
            update_devices_status(room, status)
            return JsonResponse({"ok": True, "room": room, "status": status})
        except Exception as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=500)
    return JsonResponse({"ok": False, "error": "Method not allowed"}, status=405)
