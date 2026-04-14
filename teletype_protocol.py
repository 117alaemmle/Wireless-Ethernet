import numpy as np

# ==============================================================================
# PHYSICAL LAYER CONSTANTS (Historical RTTY Standard)
# ==============================================================================

# 45.45 Baud translates to exactly 60 Words Per Minute (WPM). 
# This was the physical speed limit of the mechanical Teletype Model 15.
# Any faster, and the metal type-bars would physically jam together.
BAUD_RATE = 45.45  
BIT_TIME = 1.0 / BAUD_RATE  

# Frequency Shift Keying (FSK) Tones
# The transmitter stays on constantly, shifting between these two audio pitches.
# The 170 Hz difference between them is the standard "Shift" for Amateur Radio.
#MARK_FREQ = 2125.0   # The "1" state. Also the default resting/idle tone.
#SPACE_FREQ = 2295.0  # The "0" state. Used for the Start Bit and data zeroes.

# Shifted from 2125 Hz up to 100,000 Hz to escape the 0 Hz LO Leakage.
MARK_FREQ = 100000.0   
SPACE_FREQ = 100170.0

# ==============================================================================
# ITA2 (BAUDOT-MURRAY) PROTOCOL CONSTANTS
# ==============================================================================

# Mechanical State Shifts
LTRS_SHIFT = '11111'  # Shifts the typebasket to print A-Z
FIGS_SHIFT = '11011'  # Shifts the typebasket to print 0-9 and punctuation

# Non-Printing / Formatting Controls
SPACE_CHAR = '00100'  # Advances the carriage one space
CR_CHAR    = '01000'  # Carriage Return (Slam head to the left)
LF_CHAR    = '00010'  # Line Feed (Roll paper up)
NULL_CHAR  = '00000'  # Blank tape (Do nothing)

# The Complete 32-State Dictionary (Bit 1 to Bit 5 order)
CHAR_TO_BITS = {
    # Letters (Require the machine to be in LTRS state)
    'A':'11000', 'B':'10011', 'C':'01110', 'D':'10010', 'E':'10000',
    'F':'10110', 'G':'01011', 'H':'00101', 'I':'01100', 'J':'11010',
    'K':'11110', 'L':'01001', 'M':'00111', 'N':'00110', 'O':'00011',
    'P':'01101', 'Q':'11101', 'R':'01010', 'S':'10100', 'T':'00001',
    'U':'11100', 'V':'01111', 'W':'11001', 'X':'10111', 'Y':'10101',
    'Z':'10001',
    
    # Figures (Require the machine to be in FIGS state)
    '-':'11000', '?':'10011', ':':'01110', '$':'10010', '3':'10000',
    '!':'10110', '&':'01011', '#':'00101', '8':'01100', "'":'11010',
    '(':'11110', ')':'01001', '.':'00111', ',':'00110', '9':'00011',
    '0':'01101', '1':'11101', '4':'01010', '5':'00001', '7':'11100',
    ';':'01111', '2':'11001', '/':'10111', '6':'10101', '"':'10001'
}

# Reverse lookup tables for the receiver's DSP logic
BITS_TO_LTRS = {v: k for k, v in CHAR_TO_BITS.items() if k.isalpha()}
BITS_TO_FIGS = {v: k for k, v in CHAR_TO_BITS.items() if not k.isalpha()}


def generate_fsk_signal(message, samp_rate):
    """
    Translates a text string into a continuous FSK complex NumPy array,
    automatically injecting mechanical state shifts (LTRS/FIGS) where needed.
    """
    # 30 bits (~660ms) of 'Mark' tone. This "wakes up" the receiver and 
    # gives the SDR amplifier time to stabilize before data arrives.
    bit_sequence = ['1'] * 60 
    
    # Teletypes conventionally default to Letters mode on startup
    current_state = 'LTRS' 
    
    for char in message.upper():
        if char == ' ':
            bits = SPACE_CHAR
        elif char == '\n':
            # Map Python newlines to the historical Carriage Return + Line Feed sequence
            bit_sequence.extend(['0'] + list(CR_CHAR) + ['1', '1'])
            bit_sequence.extend(['0'] + list(LF_CHAR) + ['1', '1'])
            continue
        else:
            is_letter = char.isalpha()
            target_state = 'LTRS' if is_letter else 'FIGS'
            
            # Inject a mechanical shift command if the character requires a different state
            if current_state != target_state:
                shift_bits = LTRS_SHIFT if target_state == 'LTRS' else FIGS_SHIFT
                bit_sequence.extend(['0'] + list(shift_bits) + ['1', '1'])
                current_state = target_state
                
            bits = CHAR_TO_BITS.get(char, SPACE_CHAR) 
            
        # Frame the character: [Start Bit (0)] + [5 Data Bits] + [2 Stop Bits (11)]
        bit_sequence.append('0')      
        bit_sequence.extend(list(bits)) 
        bit_sequence.extend(['1', '1']) 

    # Add 30 bits of 'Mark' tone to hold the line open and protect the final character as done in teletypes.
    bit_sequence.extend(['1'] * 30)

    # DSP Math: Generate the actual radio wave frequencies based on the bits
    samples_per_bit = int(samp_rate * BIT_TIME)
    total_samples = len(bit_sequence) * samples_per_bit
    t = np.arange(total_samples) / samp_rate
    
    freqs = np.zeros(total_samples)
    for i, bit in enumerate(bit_sequence):
        start_idx = i * samples_per_bit
        end_idx = start_idx + samples_per_bit
        freqs[start_idx:end_idx] = MARK_FREQ if bit == '1' else SPACE_FREQ

    # Integrate frequency to continuous phase to avoid popping artifacts, then convert to Complex IQ
    phase = 2.0 * np.pi * np.cumsum(freqs) / samp_rate
    samples = 0.5 * np.exp(1j * phase) * (2**14)
    
    return samples, (len(bit_sequence) * BIT_TIME)


def decode_fsk_packet(samples, samp_rate):
    """
    Scans a captured FSK packet waveform, hunting for Start Bits, 
    and decodes the ITA2 bits while tracking the mechanical shift state.
    """
    baud_rate = 45.45
    samples_per_bit = int(samp_rate / baud_rate)
    
    # =========================================================================
    # 1. DYNAMIC FFT CALIBRATION
    # =========================================================================
    # The first part of the packet is a pure Mark warmup tone.
    # We use an FFT to find the EXACT frequency the hardware drifted to!
    start_cal = int(samp_rate * 0.05)
    end_cal = int(samp_rate * 0.20)
    
    if len(samples) < end_cal:
        return "" # Runt packet, ignore
        
    warmup = samples[start_cal:end_cal]
    warmup = warmup - np.mean(warmup) # Clear DC for a clean FFT
    
    fft_vals = np.abs(np.fft.fft(warmup))
    freqs = np.fft.fftfreq(len(warmup), 1.0/samp_rate)
    
    # Look for the peak between 50kHz and 150kHz
    search_band = (freqs > 50000.0) & (freqs < 150000.0)
    valid_freqs = freqs[search_band]
    valid_ffts = fft_vals[search_band]
    
    if len(valid_ffts) == 0:
        return ""
        
    measured_mark = valid_freqs[np.argmax(valid_ffts)]
    measured_space = measured_mark + 170.0 # Space is physically tied to +170 Hz
    
    # =========================================================================
    # 2. DUAL-FILTER NON-COHERENT AM DEMODULATION
    # =========================================================================
    t = np.arange(len(samples)) / samp_rate
    
    # Shift both tones down to exactly 0 Hz
    mark_baseband = samples * np.exp(-1j * 2 * np.pi * measured_mark * t)
    space_baseband = samples * np.exp(-1j * 2 * np.pi * measured_space * t)
    
    # Razor-tight Low Pass Filter. 
    # A moving average of exactly 1/170th of a second perfectly destroys 
    # the crosstalk between the Mark and Space channels!
    filter_len = int(samp_rate / 170.0) 
    filter_kernel = np.ones(filter_len) / filter_len
    
    mark_filtered = np.convolve(mark_baseband, filter_kernel, mode='same')
    space_filtered = np.convolve(space_baseband, filter_kernel, mode='same')
    
    # 3. COMPARE MAGNITUDES (Which tone is louder?)
    is_mark = np.abs(mark_filtered) > np.abs(space_filtered)
    
    # =========================================================================
    # 4. DECODE THE BITSTREAM
    # =========================================================================
    decoded_text = ""
    current_state = 'LTRS' 
    
    idx = 1
    total_samples = len(is_mark)
    
    # Scan the entire radio wave packet
    while idx < total_samples - (samples_per_bit * 8): 
        # Detect a Falling Edge (Transition from Mark to Space) -> START BIT!
        if not is_mark[idx] and is_mark[idx - 1]:
            
            # Jump 1.5 bits forward to land exactly in the center of Data Bit 1
            bit_idx = idx + int(1.5 * samples_per_bit)
            bits = ""
            for _ in range(5): 
                if bit_idx >= total_samples: break
                bits += '1' if is_mark[bit_idx] else '0'
                bit_idx += samples_per_bit 
                
            # Verify the Stop Bit (Must be a Mark)
            stop_idx = bit_idx
            if stop_idx < total_samples and is_mark[stop_idx]:
                
                # --- Mechanical State Machine Router ---
                if bits == LTRS_SHIFT:
                    current_state = 'LTRS'
                elif bits == FIGS_SHIFT:
                    current_state = 'FIGS'
                elif bits == SPACE_CHAR:
                    decoded_text += ' '
                elif bits == CR_CHAR or bits == LF_CHAR or bits == NULL_CHAR:
                    pass 
                else:
                    if current_state == 'LTRS':
                        decoded_text += BITS_TO_LTRS.get(bits, '?')
                    else:
                        decoded_text += BITS_TO_FIGS.get(bits, '?')
                
                # Jump forward to resume hunting after the stop bit
                idx = stop_idx + int(0.5 * samples_per_bit)
            else:
                idx += 1 
        else:
            idx += 1
            
    return decoded_text.strip()

""" How This Engineering Works

    Carrier Sense vs. Bit Sync: In the Morse (OOK) protocol, when pwr > THRESHOLD, a pulse had officially started. In Teletype, the transmitter turns on and sends a continuous "Mark" tone to hold the line open before it starts typing. Our DSP math solves this by ignoring the power jump and mathematically scanning the wave for the exact microsecond the frequency shifts to "Space."

    Center Sampling: Instead of averaging the whole bit, center_idx targets the mathematical center of the bit period. This is exactly how mechanical teletype machines worked—a spinning distributor cam would strike a contact pin exactly in the middle of the line signal to avoid the "slop" or static on the edges of the pulse.

    Phase Unwrapping: Because radio waves are circular (represented as ejθ), their phase jumps violently from +π to −π at the bottom of the wave. The np.unwrap() function stitches those jumps together into a continuous line so the derivative (np.diff) doesn't create massive false frequency spikes.

With this in place, your teletype_rx.py decoder will now correctly assemble these characters into strings and pass them up to the GUI. """
