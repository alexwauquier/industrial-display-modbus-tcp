import time
import requests
from pymodbus.client import ModbusTcpClient

IP = "DISPLAY_IP"
PORT = 0
UNIT_ID = 1
START_REGISTER_LINE1 = 1
START_REGISTER_LINE2 = 13
DISPLAY_WIDTH = 12

BASE_URL = "https://example.com"
LOGIN_URL = f"{BASE_URL}/api/auth/login/employee"
SENSORS_URL = f"{BASE_URL}/api/sensors"
MEASUREMENTS_URL = lambda sid: f"{BASE_URL}/api/sensors/{sid}/measurements"

USERNAME = "USER_USERNAME"
PASSWORD = "USER_PASSWORD"
token = None

def string_to_registers_utf8(s):
    b = s.encode('utf-8')
    registers = []
    for i in range(0, len(b), 2):
        high = b[i]
        low = b[i+1] if i+1 < len(b) else 0
        reg = (high << 8) + low
        registers.append(reg)
    return registers

def get_token():
    try:
        res = requests.post(LOGIN_URL, json={"username": USERNAME, "password": PASSWORD})
        res.raise_for_status()
        return res.json()["data"]["token"]
    except Exception as e:
        print("[ERROR] Authentication:", e)
        return None

def with_token_refresh(api_func):
    def wrapper(*args, **kwargs):
        global token
        headers = {"Authorization": f"Bearer {token}"}
        response = api_func(*args, headers=headers, **kwargs)
        if response.status_code == 401:
            token = get_token()
            if not token:
                print("[ERROR] Token expired and renewal failed.")
                return None
            headers = {"Authorization": f"Bearer {token}"}
            response = api_func(*args, headers=headers, **kwargs)
        return response
    return wrapper

@with_token_refresh
def get_sensors_response(*, headers):
    return requests.get(SENSORS_URL, headers=headers)

@with_token_refresh
def get_measurement_response(sensor_id, *, headers):
    return requests.get(MEASUREMENTS_URL(sensor_id), headers=headers)

def get_sensors_by_room():
    res = get_sensors_response()
    if not res or res.status_code != 200:
        return {}
    sensors = res.json()["data"]["sensors"]
    rooms = {}
    for sensor in sensors:
        room = sensor["space"]["name"]
        sensor_id = sensor["id"]
        sensor_type = sensor["type"]["id"]
        if room not in rooms:
            rooms[room] = {}
        if sensor_type == "CT":
            rooms[room]["temp"] = sensor_id
        elif sensor_type == "RH":
            rooms[room]["hum"] = sensor_id
    return rooms

def get_latest_value(sensor_id):
    res = get_measurement_response(sensor_id)
    if not res or res.status_code != 200:
        return None
    measurements = res.json()["data"]["measurements"]
    return float(measurements[0]["value"]) if measurements else None

def display_line(client, text, line=1):
    registers = string_to_registers_utf8(text.ljust(DISPLAY_WIDTH)[:DISPLAY_WIDTH])
    addr = START_REGISTER_LINE1 if line == 1 else START_REGISTER_LINE2
    response = client.write_registers(address=addr, values=registers, slave=UNIT_ID)
    if response.isError():
        print(f"[ERROR] Line writing {line}:", response)

if __name__ == "__main__":
    token = get_token()
    if not token:
        print("Unable to retrieve token.")
        exit(1)

    client = ModbusTcpClient(IP, port=PORT)
    if not client.connect():
        print("Modbus connection error.")
        exit(1)

    try:
        rooms = get_sensors_by_room()
        if not rooms:
            print("No sensors recovered.")
            exit(1)

        while True:
            for room, sensors in rooms.items():
                if "temp" in sensors and "hum" in sensors:
                    temp = get_latest_value(sensors["temp"])
                    hum = get_latest_value(sensors["hum"])

                    if temp is None or hum is None:
                        display_line(client, "Sensor error", line=1)
                        display_line(client, " ", line=2)
                        time.sleep(5)
                        continue

                    line1 = room[:DISPLAY_WIDTH]
                    line2 = "{:.1f}C  {:.1f}%".format(temp, hum).ljust(DISPLAY_WIDTH)

                    display_line(client, line1, line=1)
                    display_line(client, line2, line=2)

                    time.sleep(10)

    finally:
        client.close()
