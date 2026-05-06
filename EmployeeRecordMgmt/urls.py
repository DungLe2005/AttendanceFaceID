"""EmployeeRecordMgmt URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from employee.views import *
from facerecognition.views import *
from django.conf.urls import include
from django.conf.urls.static import static
from django.conf import settings


urlpatterns = [
    path("device/new/", add_device, name="add_device"),
    path("admin/", admin.site.urls),
    path("load/", load, name="load"),
    path("logout", Logout, name="logout"),
    path("facerecognition/", include("facerecognition.urls")),
    path("", include("Auth_app.urls")),
    path("admin_home/", admin_home, name="admin_home"),
    # path('', demorecognition),
    path("demorecognition/face_recognition", face_recognition, name="run_recognition"),
    path("demorecognition/face_detection/", face_detection, name="run_detection"),
    path("demorecognition/train/", train, name="run_train"),
    path("manager_users/", manager_User, name="manager_users"),
    path("update_Permission/<int:id>/", updatePermission, name="update_Permission"),
    path("cam/<str:cam_label>/", cam_page, name="cam_page"),
    path("track-post-in/", track_post_in, name="track_post_in"),
    path("track-post-out/", track_post_out, name="track_post_out"),
    path("delete_Attendence/<int:id>/", delete_Attendence, name="delete_Attendence"),
    path("delete_user/<int:id>/", delete_user, name="delete_user"),
    path("schedule_Page/", schedule_Page, name="schedule_Page"),
    path("save_Tag/", save_Tag, name="save_Tag"),
    path("save_Event/", save_Event, name="save_Event"),
    path("edit_Tag/", edit_Tag, name="edit_Tag"),
    path("edit_Event/", edit_Event, name="edit_Event"),
    path("delete_Tag/<int:id>/", delete_Tag, name="delete_Tag"),
    path("delete_Event/<int:id>/", delete_Event, name="delete_Event"),
    path("get_events/", get_events, name="get_events"),
    path("ad_train/", ad_train, name="ad_train"),
    path("ad_attendance/", attendance_page, name="ad_attendance"),
    path("manager_cam/", manager_cam, name="manager_cam"),
    path("add_cam/", add_cam, name="add_cam"),
    path("edit_cam/<int:cam_id>/", edit_cam, name="edit_cam"),
    path("delete_cam/<int:cam_id>/", delete_cam, name="delete_cam"),
    path("stream_cam/<int:cam_id>/", stream_cam, name="stream_cam"),
    path("toggle_cam/<int:cam_id>/", toggle_cam_feature, name="toggle_cam_feature"),
    path("device_dashboard/", device_dashboard, name="device_dashboard"),
    path("delete_device/<int:device_id>/", delete_device, name="delete_device"),
    path("toggle_device/<int:device_id>/", toggle_device, name="toggle_device"),
    path("toggle_room/<str:room>/", toggle_room_devices, name="toggle_room_devices"),
    path("api/device/status/", api_device_status, name="api_device_status"),
    path("api/device/sync/", api_device_sync, name="api_device_sync"),
    path(
        "api/device/update-ip/<int:device_id>/",
        update_device_ip,
        name="update_device_ip",
    ),
    path("export_attendance/", export_attendance, name="export_attendance"),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
