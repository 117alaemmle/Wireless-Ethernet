import numpy as np

def generate_manchester_signal(message, samp_rate, unit_time):
    """
    Translates a text string into a continuous OOK complex NumPy array
    using Manchester Encoding. Simulates 1973 Xerox PARC Experimental Ethernet.
    Optimized for instant execution via NumPy vectorization.
    """
    sync_bit = "1"
    
    # Convert text to raw binary bits (8-bit ASCII)
    data_bits = ''.join(format(ord(c), '08b') for c in message)
    full_bitstream = sync_bit + data_bits
    
    half_unit = unit_time / 2.0
    chips = []
    for bit in full_bitstream:
        if bit == '0':
            chips.extend([1, 0])
        else:
            chips.extend([0, 1])
            
    chips.extend([0] * 10)

    # 1. Vectorized Envelope Generation (Executes in microseconds)
    samples_per_chip = int(samp_rate * half_unit)
    
    # np.repeat instantly stretches our [1, 0] chips into full 40,000-sample blocks
    envelope = np.repeat(chips, samples_per_chip)
    total_samples = len(envelope)
    
    # 2. Vectorized Carrier Generation (Executes in microseconds)
    # The 100 kHz carrier repeats exactly every 10 samples. 
    # We calculate just 10 points, then copy-paste them to fill the whole transmission!
    base_t = np.arange(10)
    base_carrier = 0.5 * (np.exp(1j * 2 * np.pi * 0.1 * base_t)) * 2**14
    
    # np.tile copies the 10-sample block millions of times instantly
    carrier = np.tile(base_carrier, int(total_samples / 10))
    
    # 3. Apply the envelope
    rf_wave = carrier * envelope
    
    return rf_wave

# ==========================================
# EFTP (ETHERNET FILE TRANSFER PROTOCOL)
# ==========================================

def build_eftp_payload(packet_type, seq_num, data=""):
    """
    Constructs an EFTP software payload.
    packet_type: 'D' (Data), 'A' (Ack), 'X' (Abort), 'E' (End), 'R' (Endreply)
    seq_num: Integer sequence number (0-65535)
    data: The text payload (must be sliced to fit hardware MTU)
    """
    # Format a 16-bit sequence number as a 4-character hex string (e.g., '001A')
    seq_hex = f"{seq_num & 0xFFFF:04x}"
    
    # Example Output: "D001AWhen in the Course..."
    return f"{packet_type}{seq_hex}{data}"

def parse_eftp_payload(payload):
    """
    Extracts EFTP fields from a received payload string.
    Returns (packet_type, seq_num, data) or (None, None, None) if invalid.
    """
    if len(payload) < 5:
        return None, None, None
        
    packet_type = payload[0]
    
    try:
        seq_num = int(payload[1:5], 16)
    except ValueError:
        # If the sequence number isn't valid hex, the payload is corrupted
        return None, None, None
        
    data = payload[5:]
    
    return packet_type, seq_num, data