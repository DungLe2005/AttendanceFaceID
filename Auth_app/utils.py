from django.http import StreamingHttpResponse
import cv2

# Tạo lớp camera
class VideoCamera:
    def __init__(self):
        self.video = cv2.VideoCapture(0)  # mở webcam mặc định

    def __del__(self):
        self.video.release()

    def get_frame(self):
        success, frame = self.video.read()
        frame = cv2.flip(frame, 1)
        if not success:
            return None
        # Chuyển ảnh sang định dạng JPEG
        _, jpeg = cv2.imencode('.jpg', frame)
        return jpeg.tobytes()

def getCam(camera):
    while True:
        frame = camera.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')

# View stream
def stream_cam(request):
    return StreamingHttpResponse(
        getCam(VideoCamera()),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )
