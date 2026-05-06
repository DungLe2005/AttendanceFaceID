from django.urls import path
from .views import *
from .utils import *

urlpatterns = [
    path('', face_login, name='face_login'), 
    path('register/', register, name="register"),
    path('home/', home, name='home'),
    path('face_login_api/', face_login_api, name='face_login_api'),
    
]