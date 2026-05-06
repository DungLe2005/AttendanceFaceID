from django.db import models
from django.contrib.auth.models import User


class Attendance(models.Model):
    emcode = models.CharField(max_length=50)
    name = models.CharField(max_length=100)
    date = models.DateField(auto_now_add=True)
    checkin = models.TimeField(null=True, blank=True)
    checkout = models.TimeField(null=True, blank=True)
    
    # Thêm phần riêng
    subject = models.CharField(max_length=100, null=True, blank=True)  # Môn học cho SV
    shift = models.CharField(max_length=50, null=True, blank=True)  # Ca làm việc cho GV

    def __str__(self):
        return f"Attendance for {self.name} ({self.emcode})"
    
class Tag(models.Model):
    title = models.CharField(max_length=255)
    classname = models.CharField(max_length=255)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=100, blank=True, null=True)
    teacher = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.title
    
class CalendarEvent(models.Model):
    title = models.CharField(max_length=255)
    date = models.DateField()
    Class = models.CharField(max_length=255, blank=True, null=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    room = models.CharField(max_length=100, blank=True, null=True)
    teacher = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.title
    
class Device(models.Model):
    name = models.CharField(max_length=100)
    room = models.CharField(max_length=100)
    status = models.CharField(max_length=10, default="off")
    ip_address = models.CharField(max_length=50, blank=True, null=True, help_text="Địa chỉ IP của ESP32")

    def __str__(self):
        return self.name
    
class TimeOffDevice(models.Model):
    room = models.CharField(max_length=100)
    time = models.TimeField()

    def __str__(self):
        return f"TimeOff for {self.room}"

class IPCamera(models.Model):
    CAM_TYPES = [
        ("IN", "Điểm danh VÀO"),
        ("OUT", "Điểm danh RA")
    ]
    name = models.CharField(max_length=100)
    ip_address = models.CharField(max_length=255, help_text="Vd: http://192.168.1.100:81/stream")
    cam_type = models.CharField(max_length=10, choices=CAM_TYPES, default="IN")
    status = models.BooleanField(default=False, help_text="Bật/Tắt stream")
    attendance_enabled = models.BooleanField(default=True, help_text="Bật/Tắt chức năng điểm danh")
    tracking_enabled = models.BooleanField(default=True, help_text="Bật/Tắt chức năng phát hiện người lạ")

    def __str__(self):
        return f"{self.name} ({self.cam_type}) - {self.ip_address}"
