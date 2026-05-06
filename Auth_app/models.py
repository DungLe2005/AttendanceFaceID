from django.db import models
from django.contrib.auth.models import User

# Create your models here.
class Users(models.Model):
    GENDER_CHOICES = [
        ('Nam', 'Nam'),
        ('Nữ', 'Nữ'),
        ('Khác', 'Khác'),
    ]
    ROLL_CHOICES = [
        ('Admin', 'Admin'),
        ('Teacher', 'Teacher'),
        ('Student', 'Student')
    ]
    # Liên kết với user (mỗi nhân viên 1 tài khoản)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee_detail')
    full = models.CharField(max_length=50)
    
    roll = models.CharField(max_length=10, choices=ROLL_CHOICES, default='Student')
    
    # Mã nhân viên
    emcode = models.CharField(max_length=50, unique=True)
    
    Class = models.CharField(max_length=50, blank=True, null=True)

    # Thông tin cơ bản
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='Khác')

    # Ảnh khuôn mặt chính (ảnh được chụp khi đăng ký)
    face_image = models.ImageField(upload_to='faces/', blank=True, null=True)

    # Ngày tạo hồ sơ
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.emcode}"