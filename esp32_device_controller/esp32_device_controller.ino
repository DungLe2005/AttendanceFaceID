/*
 * ============================================================
 *  ESP32 — Child API Server (Push Model)
 *  Giao tiếp: Django gọi trực tiếp tới ESP32 qua HTTP GET
 * ============================================================
 */

#include <WiFi.h>
#include <WebServer.h>
#include <ArduinoJson.h>

// ===================== CẤU HÌNH =====================

// WiFi
const char* WIFI_SSID     = "Huynh Chung";       // Đổi tên WiFi
const char* WIFI_PASSWORD = "0917155223";            // Đổi mật khẩu

// Chân GPIO
const int FAN_PIN = 5;   // GPIO 5 → Transistor → Quạt
const int LED_PIN = 2;   // GPIO 2 → Transistor → LED

int pwmFreq = 25000;
int pwmResolution = 8;

// Khởi tạo Server ở cổng 80
WebServer server(80);

// ===================== BIẾN GLOBAL =====================
bool currentFanState = false;
bool currentLedState = false;

// ===================== HÀM XỬ LÝ API =====================

// Endpoint: /control?fan=on&led=off
void handleControl() {
    bool changed = false;

    if (server.hasArg("fan")) {
      String val = server.arg("fan");

      if (val == "off") {
          ledcDetach(FAN_PIN);           // 🔥 QUAN TRỌNG
          pinMode(FAN_PIN, OUTPUT);
          digitalWrite(FAN_PIN, LOW);    // ép tắt thật
          currentFanState = false;
      } else {
          ledcAttach(FAN_PIN, pwmFreq, pwmResolution);
          ledcWrite(FAN_PIN, 80);       // bật
          currentFanState = true;
      }
  }

    if (server.hasArg("led")) {
        String val = server.arg("led");
        currentLedState = (val == "on");
        digitalWrite(LED_PIN, currentLedState ? LOW : HIGH);
        Serial.printf("🔄 LED: %s\n", currentLedState ? "TẮT" : "BẬT");
        changed = true;
    }

    String response = "{\"status\":\"ok\", \"fan\":\"" + String(currentFanState ? "on" : "off") + "\", \"led\":\"" + String(currentLedState ? "on" : "off") + "\"}";
    server.send(200, "application/json", response);
}

// Endpoint: /status
void handleStatus() {
    StaticJsonDocument<128> doc;
    doc["fan"] = currentFanState ? "on" : "off";
    doc["led"] = currentLedState ? "on" : "off";
    doc["ip"] = WiFi.localIP().toString();

    String response;
    serializeJson(doc, response);
    server.send(200, "application/json", response);
}

// ===================== HÀM SETUP =====================
void setup() {
    Serial.begin(9600);
    Serial.println("\n========================================");
    Serial.println("  ESP32 Child API — Khởi động");
    Serial.println("========================================");

    // Cấu hình chân output
    // ledcAttach(FAN_PIN, pwmFreq, pwmResolution);
    pinMode(LED_PIN, OUTPUT);

    pinMode(FAN_PIN, OUTPUT);
    digitalWrite(FAN_PIN, LOW); // đảm bảo tắt thật
    ledcAttach(FAN_PIN, pwmFreq, pwmResolution);

    // Tắt tất cả khi khởi động
    ledcWrite(FAN_PIN, 0);
    digitalWrite(LED_PIN, HIGH);

    // Kết nối WiFi
    connectWiFi();

    // Đăng ký các endpoint
    server.on("/control", HTTP_GET, handleControl);
    server.on("/status", HTTP_GET, handleStatus);
    
    // Bắt đầu server
    server.begin();
    Serial.println("🚀 HTTP Server đã sẵn sàng nhận lệnh từ Django.");
}

// ===================== HÀM LOOP =====================
void loop() {
    // Kiểm tra kết nối WiFi
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("⚠ Mất kết nối WiFi — Đang reconnect...");
        connectWiFi();
    }

    // Xử lý các request từ client (Django)
    server.handleClient();
}

// ===================== KẾT NỐI WIFI =====================
void connectWiFi() {
    Serial.printf("📡 Đang kết nối WiFi: %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n✅ Đã kết nối! IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.println("👉 Hãy copy IP này vào Dashboard Django để điều khiển.");
    } else {
        Serial.println("\n❌ Không thể kết nối WiFi. Thử lại sau 5 giây...");
        delay(5000);
    }
}
