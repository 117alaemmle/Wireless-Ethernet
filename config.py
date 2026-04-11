import os
import uuid

# ==============================================================================
# OS-LEVEL TIMER FIX FOR WINDOWS 10
# Forces the Windows scheduler to 1ms resolution so time.sleep() doesn't stutter.
# ==============================================================================
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

def get_node_identity():
    """Reads the PC's MAC address and assigns the 3-character Node ID."""
    mac_num = uuid.getnode()
    mac_hex = ':'.join(['{:02x}'.format((mac_num >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])
    
    print(f"Hardware MAC Address Detected: {mac_hex}")
    
    # --- MAC ADDRESS DICTIONARY ---
    known_nodes = {
        "44:fa:66:57:b0:3a": "001",  # Windows 11 Laptop
        "58:cd:c9:11:b5:94": "002"   # Windows 10 Laptop
    }
    
    return known_nodes.get(mac_hex, "003")

# --- Global Hardware & Protocol Configuration ---
MY_ADDRESS = get_node_identity()
URI = "ip:192.168.2.1"
FREQ = 433e6
SAMP_RATE = 1e6

# Timing Configurations
UNIT_TIME = 0.08         # 15 WPM for Marconi
ETHERNET_UNIT_TIME = 0.002 # 500 bits per second for Ethernet

# Packet Configurations
ADDR_LEN = 3