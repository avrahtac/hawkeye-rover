#include <WiFi.h>
#include <WiFiUdp.h>


const char* ssid     = "Airtel_Chitale's";       
const char* password = "Chitale@123";   

WiFiUDP udp;
const unsigned int localPort = 8888; 
char packetBuffer[255]; 


const int LED_PIN = 2;              
unsigned long lastPacketTime = 0;   
const unsigned long timeoutPeriod = 2000; 

// --- Motor Pins ---
const int IN1 = 26; const int IN2 = 27;
const int IN3 = 14; const int IN4 = 12;
const int ENA = 32; const int ENB = 33;
int carSpeed = 255; 

void setup() {
  Serial.begin(115200);
  
  pinMode(LED_PIN, OUTPUT);
  pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT);
  pinMode(ENA, OUTPUT); pinMode(ENB, OUTPUT);
  
  digitalWrite(LED_PIN, LOW); // Start with light OFF
  stopMotors();

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  
  Serial.println("\n[CONNECTED] Successfully joined network!");
  Serial.print("ESP32 IP Address: ");
  Serial.println(WiFi.localIP());

  udp.begin(localPort);
}

void loop() {
  // Check if a network packet has arrived
  int packetSize = udp.parsePacket();
  if (packetSize) {
    int len = udp.read(packetBuffer, 255);
    if (len > 0) {
      packetBuffer[len] = 0; 
    }
    
    char command = packetBuffer[0];
    Serial.print("Network Command Received: ");
    Serial.println(command);

    // ═══════════════════════════════════════════════════════
    //  VIRTUAL CONNECTION LIGHT TRIGGER
    // ═══════════════════════════════════════════════════════
    lastPacketTime = millis();    // Refresh the heartbeat timer
    digitalWrite(LED_PIN, HIGH);  // Turn blue light ON because Python is talking to   us

    if (command == 'F') {
      moveForward();
    } 
    else if (command == 'S') {
      stopMotors();
    }
  }

  // ═══════════════════════════════════════════════════════
  //  TIMEOUT FAILSAFE (If Python disconnects or closes)
  // ═══════════════════════════════════════════════════════
  if (millis() - lastPacketTime > timeoutPeriod && digitalRead(LED_PIN) == HIGH) {
    digitalWrite(LED_PIN, LOW);   // Turn blue light OFF (Connection lost)
    stopMotors();                 // Force safety stop so it doesn't crash into a wall
    Serial.println("[WARN] Python connection lost! Stopping motors.");
  }
}

void moveForward() {
  analogWrite(ENA, carSpeed); 
  analogWrite(ENB, carSpeed);
  digitalWrite(IN1, HIGH); digitalWrite(IN2, LOW);
  digitalWrite(IN3, HIGH); digitalWrite(IN4, LOW);
}

void stopMotors() {
  analogWrite(ENA, 0); analogWrite(ENB, 0);
  digitalWrite(IN1, LOW); digitalWrite(IN2, LOW);
  digitalWrite(IN3, LOW); digitalWrite(IN4, LOW);
}