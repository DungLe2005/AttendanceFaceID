from django.urls import path
from .views import *

urlpatterns = [
    path('', demorecognition),
    path('demorecognition/face_recognition',face_recognition,name='run_recognition'),
    path('demorecognition/face_detection/',face_detection,name='run_detection'),
    path('demorecognition/train/',train,name='run_train'),
]
