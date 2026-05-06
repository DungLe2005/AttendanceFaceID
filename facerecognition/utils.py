from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from django.http import HttpResponse
import cv2
import time
from datetime import datetime, timedelta
import os
from . import FacialRecognition 
from django.contrib import messages
import subprocess
import threading
import unidecode
from django.http import HttpResponse
import json,pandas
import openpyxl
from openpyxl.styles import Alignment

currentPythonFilePath = os.getcwd()
        
#sử dụng .replace('\\','/') để thay đổi dấu / đg dẫn.

os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
# Load face detector and recognizer
detector = FacialRecognition.FaceDetector(
    minsize=20,
    threshold=[0.6, 0.7, 0.7],
    factor=0.709,
    gpu_memory_fraction=0.6,
    detect_face_model_path=currentPythonFilePath+'/static/align'.replace('\\','/'),
    facenet_model_path=currentPythonFilePath+'/static/Models/20180402-114759.pb'.replace('\\','/')
)
recognizer = FacialRecognition.FaceRecognition(classifier_path= currentPythonFilePath+'/static/Models/facemodel.pkl'.replace('\\','/'))
# Initialize barcode reader
barcode_reader = FacialRecognition.BarcodeReader(verbose=False)

#hàm mở camera và nhận diện khuôn mặt
def face_recognition(request):
    # cv2.namedWindow('Nhan Dien Khuon Mat')
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return HttpResponse("Khong the mo camera")
    # Lưu ý: Vòng lặp while True này sẽ làm treo worker của Django.
    # Trong môi trường web, nên sử dụng các endpoint API (như track-post) 
    # thay vì mở cửa sổ OpenCV trực tiếp trên server.
    while True:
        try:
            ret, frame = cap.read()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Read barcodes from the image
            barcodes, imgbarcode = barcode_reader.read_barcodes(rgb)      
            # Detect faces in the frame
            faces, _= detector.get_faces(rgb)
            for face in faces:
                x1, y1, x2, y2 = face[:4]

                # Get face image
                face_img = rgb[int(y1):int(y2), int(x1):int(x2), :]
                #lưu ảnh vào thư mục static
                

                # Get face embeddings
                embeddings = detector.get_embeddings(face_img)

                # Recognize face
                name, prob = recognizer.recognize_face(embeddings)
                cv2.imwrite(currentPythonFilePath+'/static/'+name+'.jpg'.replace('\\','/'),face_img)
                cv2.rectangle(imgbarcode, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                cv2.putText(imgbarcode, "{} {:.2f}".format(name, prob), (int(x1), int(y1) - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            # cv2.imshow('Nhan Dien Khuon Mat', imgbarcode)
        except Exception as e:
            continue

        # Check if window is closed
        # if cv2.getWindowProperty('Nhan Dien Khuon Mat', cv2.WND_PROP_VISIBLE) < 1:
        #    break
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cap.release()
    # cv2.destroyAllWindows()
    return HttpResponse(name,barcodes)

def tinh_thoi_gian_lam_viec(danh_sach_check_in_out):
    so_lan_check_in = len(danh_sach_check_in_out) // 2
    thoi_gian_ca_sang = timedelta()
    thoi_gian_ca_chieu = timedelta()

    for i in range(so_lan_check_in):
        index_check_in = i * 2
        index_check_out = index_check_in + 1

        check_in = to_date_time(danh_sach_check_in_out[index_check_in])
        check_out = to_date_time(danh_sach_check_in_out[index_check_out])

        # Xác định thời điểm chia ca (12:00 PM)
        ca_chia_ca = check_in.replace(hour=12, minute=0, second=0)

        # Tính thời gian làm việc của ca sáng
        if check_in < ca_chia_ca:
            if check_out <= ca_chia_ca:
                thoi_gian_ca_sang += check_out - check_in
            else:
                thoi_gian_ca_sang += ca_chia_ca - check_in

        # Tính thời gian làm việc của ca chiều
        if check_out >= ca_chia_ca:
            if check_in >= ca_chia_ca:
                thoi_gian_ca_chieu += check_out - check_in
            else:
                thoi_gian_ca_chieu += check_out - ca_chia_ca

    return thoi_gian_ca_sang, thoi_gian_ca_chieu

#hàm date range
def daterange(start_date, end_date):
    for n in range(int ((end_date - start_date).days)+1):
        yield start_date + timedelta(n)

def to_date_dmy(date):
    return datetime.strptime(date, '%d/%m/%Y')

def to_date_ymd(date):
    return datetime.strptime(date, '%Y-%m-%d')

def to_date_time(date):
    return datetime.strptime(date, '%d/%m/%Y %H:%M:%S')

def to_time(time):
    return datetime.strptime(time, '%H:%M:%S').time()

def calc_time(delta):
    return delta.total_seconds() / 3600


def query_attendance_by_emcode(empcode,startDate,endDate):
    time_work = []
    for date in daterange(startDate,endDate):
        ds=find_attendance(empcode,date)
        sang,chieu=tinh_thoi_gian_lam_viec(ds)
        time_work.append([empcode,date.strftime("%d/%m/%Y"),calc_time(sang),calc_time(chieu)])
    return time_work


#hàm lấy ảnh từ video cách mỗi 10s 1 lần và lưu vào thư mục static, đọc video từ dường dẫn
def get_frame(request,path_video):
    # Create named window
    # cv2.namedWindow('Lay Anh Tu Video')
    cap = cv2.VideoCapture(path_video)
    if not cap.isOpened():
        return HttpResponse("Không thể đọc video")
    count = 0
    while True:
        try:
            ret, frame = cap.read()
            #xác định thời gian hiện tại của video
            currentframe = cap.get(cv2.CAP_PROP_POS_MSEC)
        except Exception as e:
            continue

        # Check if window is closed
        # if cv2.getWindowProperty('Lay Anh Tu Video', cv2.WND_PROP_VISIBLE) < 1:
        #    break
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cap.release()
    # cv2.destroyAllWindows()
    return HttpResponse(count)
   

def face_detection(request):
    
    folder_name = request.GET.get('name')
    folder_path = os.path.join('./static/data/', folder_name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        # messages.success(request, 'Tạo thư mục thành công')
    # cv2.namedWindow('Phat Hien Khuon Mat')
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        return HttpResponse("Khong the mo camera")
    count = 0
    start = True
    folder_path = os.path.join(currentPythonFilePath, 'static', 'data', folder_name)
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
    while True:
        if count >= 10:
            messages.success(request, 'Có dữ liệu mới được thêm vào.')
            break
        try:
            ret, frame = cap.read()
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            # Detect faces in the frame
            faces, _ = detector.get_faces(rgb)

            for face in faces:
                faces_found= faces.shape[0]
                if start== True:
                    time.sleep(5)
                    start= False
                if faces_found > 1:
                        cv2.putText(rgb, "Chi Mot Khuon Mat", (0, 100), cv2.FONT_HERSHEY_COMPLEX_SMALL,
                                    1, (255, 255, 255), thickness=1, lineType=2)
                elif faces_found > 0:
                    x1, y1, x2, y2 = face[:4]
                    count += 1
                    # # Get face image
                    # face_img = rgb[int(y1):int(y2), int(x1):int(x2), :]
                    image_path = os.path.join(folder_path, folder_name +'_'+ str(count) + '.jpg')
                    cv2.imwrite(image_path, frame)
                    #draw bbox
                    show = cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    # cv2.imshow('Phat Hien Khuon Mat', show)
                    
        except Exception as e:
            continue

        # Check if window is closed
        # if cv2.getWindowProperty('Phat Hien Khuon Mat', cv2.WND_PROP_VISIBLE) < 1:
        #    break
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cap.release()
    # cv2.destroyAllWindows()
    messages.success(request, 'Có dữ liệu mới được thêm vào.')
    return HttpResponse('success')

def train(request):
    currentPythonFilePath = os.getcwd().replace('\\','/')
    print('Current Python File Path: ', currentPythonFilePath)
    print('data augmentation')
    cmdAug= 'python "{}"/facerecognition/Data_Augmentation.py'.format(currentPythonFilePath)

    resultAug = subprocess.run(cmdAug, stdout=subprocess.PIPE, shell=True)

    print(resultAug.stdout)
    print('align dataset')
    
    cmdAlign = 'python "{}"/facerecognition/align_dataset_mtcnn.py "{}"/static/data_process/raw/ "{}"/static/data_process/process/ "{}"/static/align --image_size 160 --margin 32 --random_order --gpu_memory_fraction 0.25'.format(currentPythonFilePath, currentPythonFilePath, currentPythonFilePath, currentPythonFilePath)

    resultAlign = subprocess.run(cmdAlign, stdout=subprocess.PIPE, shell=True)

    print(resultAlign.stdout)

    print('train classifier')

    cmdClass = 'python "{}"/facerecognition/classifier.py TRAIN "{}"/static/data_process/process "{}"/static/Models/20180402-114759.pb "{}"/static/Models/facemodel.pkl --batch_size 1000'.format(currentPythonFilePath, currentPythonFilePath, currentPythonFilePath, currentPythonFilePath)

    resultClass = subprocess.run(cmdClass, stdout=subprocess.PIPE, shell=True)

    # Print the output of the subprocess
    print(resultClass.stdout)
    train_datetime = datetime.now()

# Định dạng ngày tháng năm theo định dạng Việt Nam (dd/mm/yyyy)
    date_str = train_datetime.strftime("%d/%m/%Y")

    # Định dạng giờ theo định dạng 24 giờ (HH:MM)
    time_str = train_datetime.strftime("%H:%M")

    # Ghi thông tin vào file
    with open('time.txt', 'w',encoding='utf-8') as file:
        file.write(f'Thời gian train hoàn thành vào ngày: {date_str} {time_str}\n')
    # Return a success response
    messages.success(request, 'Train dữ liệu thành công.')
    return HttpResponse('ok luon')

            

def Gender_frame(camera):
    while True:
        try:

            frame = camera.get_frame()
        
            yield (b'--frame\r\n'
                 b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n\r\n')
            
            if camera.is_running == False:
                break
        except GeneratorExit:
            
            break
            
        except:
            pass


def data_feed():
    try:
        with open(currentPythonFilePath+'/data.txt', 'r',encoding='utf-8') as file:
            data = file.read()
        return data
    except:
        return 'Chưa có dữ liệu'