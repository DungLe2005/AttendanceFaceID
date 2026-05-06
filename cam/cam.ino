#include <esp32cam.h>
#include <WebServer.h>
#include <WiFi.h>
#include <FirebaseESP32.h>
#include <time.h>

const char* WIFI_SSID = "PHCM_NCKH";
const char* WIFI_PASS = "giangvien";

// Cấu hình Firebase
#define API_KEY "AIzaSyACWD3B8FXuONI6oWOnbTtJRT92lJDD-84"
#define DATABASE_URL "attendancefaceid-5e07a.firebaseapp.com"
#define USER_EMAIL "iotbdu@gmail.com"
#define USER_PASSWORD "123456"

FirebaseData firebaseData;
FirebaseJson json;
FirebaseConfig config;
FirebaseAuth auth;

WebServer server(80);

static auto loRes = esp32cam::Resolution::find(320, 240);
static auto hiRes = esp32cam::Resolution::find(640, 480);

void handleBmp()
{
  if (!esp32cam::Camera.changeResolution(loRes)) {
    Serial.println("SET-LO-RES FAIL");
  }

  auto frame = esp32cam::capture();
  if (frame == nullptr) {
    Serial.println("CAPTURE FAIL");
    server.send(503, "", "");
    return;
  }
  Serial.printf("CAPTURE OK %dx%d %db\n", frame->getWidth(), frame->getHeight(),
                static_cast<int>(frame->size()));

  if (!frame->toBmp()) {
    Serial.println("CONVERT FAIL");
    server.send(503, "", "");
    return;
  }
  Serial.printf("CONVERT OK %dx%d %db\n", frame->getWidth(), frame->getHeight(),
                static_cast<int>(frame->size()));

  server.setContentLength(frame->size());
  server.send(200, "image/bmp");
  WiFiClient client = server.client();
  frame->writeTo(client);
}

void serveJpg()
{
  auto frame = esp32cam::capture();
  if (frame == nullptr) {
    Serial.println("CAPTURE FAIL");
    server.send(503, "", "");
    return;
  }
  Serial.printf("CAPTURE OK %dx%d %db\n", frame->getWidth(), frame->getHeight(),
                static_cast<int>(frame->size()));

  server.setContentLength(frame->size());
  server.send(200, "image/jpeg");
  WiFiClient client = server.client();
  frame->writeTo(client);
}

void handleJpgLo()
{
  if (!esp32cam::Camera.changeResolution(loRes)) {
    Serial.println("SET-LO-RES FAIL");
  }
  serveJpg();
}

void handleJpgHi()
{
  if (!esp32cam::Camera.changeResolution(hiRes)) {
    Serial.println("SET-HI-RES FAIL");
  }
  serveJpg();
}

void handleJpg()
{
  server.sendHeader("Location", "/cam-hi.jpg");
  server.send(302, "", "");
}

void handleMjpeg()
{
  if (!esp32cam::Camera.changeResolution(hiRes)) {
    Serial.println("SET-HI-RES FAIL");
  }

  Serial.println("STREAM BEGIN");
  WiFiClient client = server.client();
  auto startTime = millis();
  int res = esp32cam::Camera.streamMjpeg(client);
  if (res <= 0) {
    Serial.printf("STREAM ERROR %d\n", res);
    return;
  }
  auto duration = millis() - startTime;
  Serial.printf("STREAM END %dfrm %0.2ffps\n", res, 1000.0 * res / duration);
}
// Lấy ngày hiện tại
String getCurrentDate() {
    time_t now = time(nullptr);
    struct tm* timeinfo = localtime(&now);

    char buffer[11];
    snprintf(buffer, sizeof(buffer), "%02d/%02d/%04d",
             timeinfo->tm_mday, timeinfo->tm_mon + 1, timeinfo->tm_year + 1900);

    return String(buffer);
}
// Khởi tạo Firebase
void initFirebase() {
    Serial.println("Đang khởi tạo Firebase...");

    config.api_key = API_KEY;
    config.database_url = DATABASE_URL;
    auth.user.email = USER_EMAIL;
    auth.user.password = USER_PASSWORD;

    Firebase.begin(&config, &auth);
    Firebase.reconnectWiFi(true);

    Serial.println("Đang chờ xác thực Firebase...");
    int attempts = 0;
    while (!Firebase.ready() && attempts < 30) {
        Serial.print(".");
        delay(500);
        attempts++;
    }
    Serial.println();

    if (Firebase.ready()) {
        Serial.println("Xác thực Firebase thành công!");
        sendIPToFirebase();
    } else {
        Serial.println("Xác thực Firebase thất bại. Kiểm tra lại thông tin.");
    }
}

void sendIPToFirebase() {
    if (!Firebase.ready()) {
        Serial.println("Firebase chưa sẵn sàng. Không thể gửi IP.");
        return;
    }

    String ipAddress = WiFi.localIP().toString();
    String updatedAt = getCurrentDate();

    json.clear();
    json.set("device_name", "ESP32CAM1");
    json.set("ip_address", ipAddress);
    json.set("status", "Connected to WiFi");
    json.set("updatedAt", updatedAt);

    String path = "/devices/ESP32CAM1";

    if (Firebase.setJSON(firebaseData, path, json)) {
        Serial.println("Gửi địa chỉ IP lên Firebase thành công!");
    } else {
        Serial.println("Lỗi khi gửi địa chỉ IP lên Firebase: " + firebaseData.errorReason());
    }
}
void setup()
{
  Serial.begin(115200);
  Serial.println();
  
  {
    using namespace esp32cam;
    Config cfg;
    cfg.setPins(pins::AiThinker);
    cfg.setResolution(hiRes);
    cfg.setBufferCount(2); // Duy trì 2 buffer để cân bằng bộ nhớ và tốc độ
    cfg.setJpeg(12);       // Tăng chất lượng nén (0-63, 10-12 là mức cân bằng tốt)

    bool ok = Camera.begin(cfg);
    Serial.println(ok ? "CAMERA OK" : "CAMERA FAIL");
  }

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
  WiFi.setSleep(false); // Tắt tiết kiệm điện WiFi để giảm ping/latency
  initFirebase();
  sendIPToFirebase();
  Serial.print("http://");
  Serial.println(WiFi.localIP());
  Serial.println("  /cam.bmp");
  Serial.println("  /cam-lo.jpg");
  Serial.println("  /cam-hi.jpg");
  Serial.println("  /cam.mjpeg");

  server.on("/cam.bmp", handleBmp);
  server.on("/cam-lo.jpg", handleJpgLo);
  server.on("/cam-hi.jpg", handleJpgHi);
  server.on("/cam.jpg", handleJpg);
  server.on("/cam.mjpeg", handleMjpeg);

  server.begin();
}

void loop()
{
  server.handleClient();
}
