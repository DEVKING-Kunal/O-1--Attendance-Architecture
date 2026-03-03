import qrcode
import psutil
import socket

def get_hotspot_ip():
    # Standard Windows Hotspot often identifies as 'Local Area Connection* X'
    # We look for the common Hotspot subnet first
    interfaces = psutil.net_if_addrs()
    for interface_name, interface_addresses in interfaces.items():
        for address in interface_addresses:
            if address.family == socket.AF_INET:
                # Check for the classic Windows Hotspot gateway
                if "192" in address.address:
                    return address.address
    
    # Fallback: Get the primary active IP if no Hotspot-specific IP found
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

ip_addr = get_hotspot_ip()
url = f"http://{ip_addr}"

print(f"Detected IP : {ip_addr}")
print(f"Generating QR Code for: {url}")

img = qrcode.make(url)
img.save("attendance_qr.png")
print("✅ Saved as attendance_qr.png!")