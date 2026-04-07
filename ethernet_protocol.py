import numpy as np

def generate_manchester_signal(message, samp_rate, unit_time):
    """
    Translates a text string into a continuous OOK complex NumPy array
    using Manchester Encoding. Simulates 1973 Xerox PARC Experimental Ethernet.
    """
    # 1. Assemble the Frame: [1-Bit Sync] + [Message]
    # Original Experimental Ethernet used a single '1' bit to wake the receiver
    sync_bit = "1"
    
    # Convert text to raw binary bits (8-bit ASCII)
    data_bits = ''.join(format(ord(c), '08b') for c in message)
    full_bitstream = sync_bit + data_bits
    
    # 2. Manchester Encoding (0 -> 10, 1 -> 01)
    half_unit = unit_time / 2.0
    chips = []
    for bit in full_bitstream:
        if bit == '0':
            chips.extend([1, 0]) # High-to-Low transition
        else:
            chips.extend([0, 1]) # Low-to-High transition
            
    # Add a "Tail" of silence to clear the buffer
    chips.extend([0] * 10)

    # 3. Generate the continuous RF waveform (OOK at 100 kHz offset)
    samples_per_chip = int(samp_rate * half_unit)
    total_samples = len(chips) * samples_per_chip
    
    t = np.arange(total_samples)
    carrier = 0.5 * (np.exp(1j * 2 * np.pi * 0.1 * t)) * 2**14
    
    envelope = np.zeros(total_samples)
    for i, chip in enumerate(chips):
        if chip == 1:
            envelope[i*samples_per_chip : (i+1)*samples_per_chip] = 1.0
            
    rf_wave = carrier * envelope
    
    return rf_wave