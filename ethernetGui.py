import os, time, random, threading, queue, uuid
import tkinter as tk
from tkinter import scrolledtext
import zlib
import numpy as np  #pip install numpy pyadi-iio
import adi
import ethernet_protocol
import marconiAudio
from tkinter import ttk  # Required for the Combobox
import teletype_protocol # New module to handle teletype.
import marconi_rx, marconi_audio #Play audio tone through PC speakers
import teletype_rx, teletype_tx
import ethernet_tx, ethernet_rx

def get_node_identity():
    """Reads the PC's MAC address and assigns the 3-character Node ID."""
    # Grab the 48-bit MAC address and format it into a standard hex string
    mac_num = uuid.getnode()
    mac_hex = ':'.join(['{:02x}'.format((mac_num >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])
    
    print(f"Hardware MAC Address Detected: {mac_hex}")
    
    # --- MAC ADDRESS DICTIONARY ---
    known_nodes = {
        "44:fa:66:57:b0:3a": "001",  # Windows 11 Laptop
        "ba:86:87:7d:26:29": "002"   # Windows 10 Laptop
    }
    
    # Return the mapped ID, or default to "003" if it's an unknown computer
    return known_nodes.get(mac_hex, "003")

# --- Configuration ---
MY_ADDRESS = get_node_identity()
URI = "ip:192.168.2.1"
FREQ = 433e6
SAMP_RATE = 1e6
#UNIT_TIME = 0.12  # Solid reliability #10 Words Per Minute for Marconi, a beginner speed.
#UNIT_TIME = 0.06 # 20 Words per minute, a professional operator's standard speed in ~1912. 
UNIT_TIME = 0.08 # 15 Words per minute, a common speed for radio operators in the early 1900s, including those on the Titanic. This speed allows for clear communication while still being efficient, especially given the heavy brass telegraph keys used at the time.
#A professional Marconi operator in the early 1900s (like the operators on the Titanic) typically cruised at 15 to 20 WPM. Their speed was physically limited by the massive, heavy brass telegraph keys used to switch the high-voltage spark-gap equipment.
#By World War II, operators using smaller keys or semi-automatic "bugs" (which used a vibrating pendulum to generate dots automatically) could comfortably send at 25 to 30 WPM, with elite operators pushing 40+ WPM.
ETHERNET_UNIT_TIME = 0.002 #500 bits per second.
#THRESHOLD = 580   # Using 'max' power logic for snappier detection
#THRESHOLD = 500 

# ==============================================================================
# OS-LEVEL TIMER FIX FOR WINDOWS 10
# Forces the Windows scheduler to 1ms resolution so time.sleep() doesn't stutter,
# preventing Morse characters from fracturing (e.g., 'O' splitting into 'M' and 'T').
# ==============================================================================
if os.name == 'nt':
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass

# Fixed-Length Header Config
ADDR_LEN = 3 

MORSE_DICT = {
    # Letters
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', 
    
    # Numbers
    '1': '.----', '2': '..---', '3': '...--', '4': '....-', '5': '.....', 
    '6': '-....', '7': '--...', '8': '---..', '9': '----.', '0': '-----', 
    
    # Punctuation
    '.': '.-.-.-',   # Period / Full Stop
    ',': '--..--',   # Comma
    '?': '..--..',   # Question Mark
    '!': '-.-.--',   # Exclamation Mark
    '-': '-....-',   # Hyphen / Minus
    '/': '-..-.',    # Slash / Fraction Bar
    '@': '.--.-.',   # At Sign (Added in 2004 by the ITU!)
    '(': '-.--.',    # Open Parenthesis
    ')': '-.--.-',   # Close Parenthesis
    ':': '---...',   # Colon
    ';': '-.-.-.',   # Semicolon
    '=': '-...-',    # Double Dash / Equals (Prosign BT - Break/Pause)
    '+': '.-.-.',    # Plus (Prosign AR - End of Message)
    '"': '.-..-.',   # Quotation Mark
    "'": '.----.',   # Apostrophe
    
    # Our software-specific word gap trigger
    ' ': '/'         
}
REVERSE_DICT = {v: k for k, v in MORSE_DICT.items() if v != '/'}

class MarconiNode:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Wireless Node {MY_ADDRESS}")
        
        # Hardware Setup
        try:
            self.sdr = adi.Pluto(URI)
            self.sdr.sample_rate = int(SAMP_RATE)
            self.sdr.tx_lo = int(FREQ)
            self.sdr.rx_lo = int(FREQ)
            self.sdr.tx_hardwaregain_chan0 = -10 #-10DB for direct wired connection
            #self.sdr.tx_hardwaregain_chan0 = 0 #0DB for antenna use, gives it a boost to be able to hear anything at all.
            self.sdr.rx_hardwaregain_chan0 = 25 #25DB gain for direct connection.
            #self.sdr.rx_hardwaregain_chan0 = 55 #bigger gain for antennas.
            self.sdr.rx_buffer_size = 500 # Increasing buffer size to prevent dropping samples
            #self.sdr.rx_buffer_size = 32768 #We need to change buffer size depending on the type of protocol. Marconi requires precise timing, smaller buffer size.
        except Exception as e:
            print(f"Hardware Error: {e}")
            
        # --- THE QUEUE ---
        # This stores (target, message) tuples
        self.tx_queue = queue.Queue()

        # --- EFTP THREAD COMMUNICATION ---
        self.ack_received_event = threading.Event()
        self.expected_ack_seq = -1

        ###########################################
        # --- Indicator Lights Setup ---
        ###########################################
        indicator_frame = tk.Frame(root)
        indicator_frame.pack(pady=5)

        # TX Light (Red when sending)
        tk.Label(indicator_frame, text="TX").pack(side="left", padx=5)
        self.tx_light = tk.Canvas(indicator_frame, width=20, height=20, bg=root["bg"], highlightthickness=0)
        self.tx_led = self.tx_light.create_oval(2, 2, 18, 18, fill="gray")
        self.tx_light.pack(side="left", padx=5)

        # RX Light (Green when signal detected)
        tk.Label(indicator_frame, text="RX").pack(side="left", padx=20)
        self.rx_light = tk.Canvas(indicator_frame, width=20, height=20, bg=root["bg"], highlightthickness=0)
        self.rx_led = self.rx_light.create_oval(2, 2, 18, 18, fill="gray")
        self.rx_light.pack(side="left", padx=5)

        ###########################
        # --- Power Meter Setup ---
        ############################

        # --- LIVE THRESHOLD FIX ---
        self.current_threshold = 100.0 # Instance variable replaces the global THRESHOLD

        meter_frame = tk.Frame(root)
        meter_frame.pack(pady=5, fill="x", padx=20)
        
        tk.Label(meter_frame, text="RX Power:").pack(side="left")
        
        # 300px wide canvas, assuming a max visual power of ~2000 for the ADALM-PLUTO
        self.pwr_canvas = tk.Canvas(meter_frame, width=300, height=20, bg="black", highlightthickness=1)
        self.pwr_canvas.pack(side="left", padx=10)
        
        # The dynamic bar (height 20)
        self.pwr_bar = self.pwr_canvas.create_rectangle(0, 0, 0, 20, fill="blue")

        self.max_graph_pwr = self.current_threshold * 4 # Adjust this if your signal regularly blows past the end of the bar
        
        # Draw the Static Scale Ticks and Labels
        for val in range(0, int(self.max_graph_pwr) + 1, int(int(self.max_graph_pwr)// 10)):
            x_pos = (val / self.max_graph_pwr) * 300
            # Small white tick line
            self.pwr_canvas.create_line(x_pos, 20, x_pos, 25, fill="white")
            # Text label for the scale
            self.pwr_canvas.create_text(x_pos, 32, text=str(val), fill="white", font=("Arial", 8))
        
        # Draw the Threshold Line
        self.thresh_x = (self.current_threshold / self.max_graph_pwr) * 300
        self.pwr_thresh_line = self.pwr_canvas.create_line(self.thresh_x, 0, self.thresh_x, 20, fill="red", width=2)

        # Add the Live Value Label next to the canvas
        self.live_pwr_label = tk.Label(meter_frame, text="0", width=6, font=("Courier", 10, "bold"), fg="blue")
        self.live_pwr_label.pack(side="left")
               
        
        self.threshold_scale = tk.Scale(
            meter_frame, 
            from_=0, to=self.max_graph_pwr, 
            orient="horizontal", 
            label="Live RX Detection Threshold", 
            command=self.update_threshold
        )
        self.threshold_scale.set(self.current_threshold)
        self.threshold_scale.pack(fill="x", padx=10)

        # Timer to prevent UI flooding
        self.last_meter_update = time.time()

        ######################################
        # Audio Controls between modes, GUI gets drawn in order it is in the code, so it goes before the GUI draw to ensure it stays on top.
        ######################################
        self.audio_mode = tk.StringVar(value="Cinema")
        audio_frame = tk.LabelFrame(root, text="Morse Code Sound Profile")
        audio_frame.pack(padx=10, pady=10, fill="x")
        
        for mode in ["Marconi", "Cinema", "Silent"]:
            tk.Radiobutton(audio_frame, text=mode, variable=self.audio_mode, value=mode).pack(side="left", padx=10)

        # Protocol Selection Drop-down
        protocol_frame = tk.LabelFrame(root, text="Transmission Protocol")
        protocol_frame.pack(padx=10, pady=5, fill="x")
        
        self.protocol_var = tk.StringVar(value="Marconi (OOK)")
        self.protocol_dropdown = ttk.Combobox(
            protocol_frame, 
            textvariable=self.protocol_var, 
            values=["Marconi (OOK)", "Teletype (FSK)", "ALOHAnet (OOK)", "Wireless Ethernet (CSMA/CA)"],
            state="readonly"
        )
        self.protocol_dropdown.pack(padx=10, pady=5, side="left")

        self.channel_busy = False
        self.last_rx_state = False  # Tracks previous state to prevent UI flooding
        self.is_transmitting = False
        self.just_finished_tx = False

        # --- Marconi (OOK) Receiver State ---
        self.m_stream = ""
        self.m_symbols = ""
        self.m_in_pulse = False
        self.m_p_start = time.time()
        self.m_s_start = time.time()

        # Initialize Decoders for decoding incoming messages
        self.marconi_decoder = marconi_rx.MarconiDecoder(UNIT_TIME, REVERSE_DICT)
        self.teletype_decoder = teletype_rx.TeletypeDecoder(SAMP_RATE)
        self.ethernet_decoder = ethernet_rx.EthernetDecoder(SAMP_RATE, ETHERNET_UNIT_TIME)

        # Initialize Transmitters
        self.teletype_transmitter = teletype_tx.TeletypeTransmitter(
            self.sdr, SAMP_RATE, self.log, self.set_led
        )
        self.ethernet_transmitter = ethernet_tx.EthernetTransmitter(
            self.sdr, SAMP_RATE, ETHERNET_UNIT_TIME, self.log, self.set_led, lambda: self.channel_busy
        )

        # --- Teletype (FSK) Receiver State ---
        self.t_buffer = np.array([], dtype=np.complex128)

        
        # GUI
        self.history = scrolledtext.ScrolledText(root, state='disabled', height=20, width=75)
        self.history.pack(padx=10, pady=10)
        self.entry = tk.Entry(root, width=75)
        self.entry.pack(padx=10, pady=(0, 10))
        self.entry.bind("<Return>", self.on_send)
        
        self.log(f"*** Node {MY_ADDRESS} Listening (Promiscuous Mode) ***")
#        threading.Thread(target=self.receiver_loop, daemon=True).start()


        # Start background threads
        threading.Thread(target=self.receiver_loop, daemon=True).start()
        time.sleep(0.5)  # Allow receiver to stabilize between hardware calls
        threading.Thread(target=self.tx_daemon, daemon=True).start()



    def log(self, message, tag="status"):
        def append():
            ts = time.strftime("[%H:%M:%S]")
            self.history.configure(state='normal')

            # Define the color palette
            self.history.tag_config("status", foreground="gray")
            self.history.tag_config("received", foreground="blue")
            self.history.tag_config("sniffed", foreground="purple")
            self.history.tag_config("error", foreground="red")
            
            # Insert the text with the assigned tag
            self.history.insert(tk.END, f"{ts} {message}\n", tag)
            self.history.configure(state='disabled')
            self.history.see(tk.END)
        self.root.after(0, append)


    # Set LED colors in a thread-safe manner depending on the action taken by the code
    def set_led(self, led_type, color):
        """Thread-safe method to change LED colors."""
        if led_type == "TX":
            self.is_transmitting = (color == "red")
        target = self.tx_led if led_type == "TX" else self.rx_led
        canvas = self.tx_light if led_type == "TX" else self.rx_light
        self.root.after(0, lambda: canvas.itemconfig(target, fill=color))

    def update_threshold(self, val):
        """Updates the math variable and moves the red line on the meter."""
        self.current_threshold = float(val)
        new_x = (self.current_threshold / self.max_graph_pwr) * 300
        self.pwr_canvas.coords(self.pwr_thresh_line, new_x, 0, new_x, 20)

    # Update the real-time power meter to display received strength.
    def update_power_meter(self, pwr):
        """Thread-safe method to update the real-time power bar graph."""
        # Cap the visual power so it doesn't draw off the edge of the canvas
        graph_pwr = min(pwr, self.max_graph_pwr)
        bar_width = (graph_pwr / self.max_graph_pwr) * 300
        
        def draw():
            self.pwr_canvas.coords(self.pwr_bar, 0, 0, bar_width, 20)
            # Turn the bar Red if it crosses the threshold, Lime if it's below
            color = "lime" if pwr > self.current_threshold else "blue"
            self.pwr_canvas.itemconfig(self.pwr_bar, fill=color)

            # Update the text label with the exact integer value
            self.live_pwr_label.config(text=f"{int(pwr)}")
            
        self.root.after(0, draw)


    def on_send(self, event):
        raw = self.entry.get().strip()
        if len(raw) < 5: return # Need at least '002 H'
        self.entry.delete(0, tk.END)
        
        target = raw[:3]
        msg = raw[3:].strip()
        #Changing method to enable enqueing of messages
        #threading.Thread(target=self.transmit, args=(target, msg), daemon=True).start()
        self.tx_queue.put((target, msg))
        self.log(f"[Queued] -> {target}: {msg}")

    def tx_daemon(self):
            while True:
                target, msg = self.tx_queue.get()
                
                # while self.channel_busy:
                #     time.sleep(random.uniform(0.5, 2.0))
                
                # Check which protocol the user has selected
                current_protocol = self.protocol_var.get()
                
                if current_protocol == "Marconi (OOK)":
                    self.transmit_marconi(target, msg)
                elif current_protocol == "Teletype (FSK)":
                    self.teletype_transmitter.transmit(target, MY_ADDRESS, msg)     
                elif current_protocol == "Wireless Ethernet (CSMA/CA)":
                    MTU_DATA_SIZE = 81
                    chunks = [msg[i:i+MTU_DATA_SIZE] for i in range(0, len(msg), MTU_DATA_SIZE)]
                    
                    seq_num = 0
                    max_retries = 5
                    transfer_failed = False
                    
                    # ------------------------------------------
                    # Phase 1: Transmit Data Chunks
                    # ------------------------------------------
                    for chunk_idx, chunk_text in enumerate(chunks):
                        payload = ethernet_protocol.build_eftp_payload('D', seq_num, chunk_text)
                        
                        success = False
                        for attempt in range(max_retries):
                            if len(chunks) > 1:
                                self.log(f"-> Sending [Part {chunk_idx+1}/{len(chunks)}] (Attempt {attempt+1})", "status")
                            else:
                                self.log(f"-> Sending Data (Attempt {attempt+1})", "status")
                                
                            self.expected_ack_seq = seq_num
                            self.ack_received_event.clear()
                            
                            self.ethernet_transmitter.transmit(target, MY_ADDRESS, payload)
                            
                            if self.ack_received_event.wait(timeout=2.5):
                                success = True
                                break 
                            else:
                                self.log(f"XX ACK {seq_num} Timeout. Retransmitting...", "error")
                        
                        if not success:
                            self.log(f"XX EFTP Transfer Failed: Target {target} unreachable.", "error")
                            transfer_failed = True
                            break 
                            
                        seq_num += 1

                    if transfer_failed:
                        continue

                    # ------------------------------------------
                    # Phase 2: Transmit End Packet
                    # ------------------------------------------
                    end_payload = ethernet_protocol.build_eftp_payload('E', seq_num)
                    end_success = False
                    
                    for attempt in range(max_retries):
                        self.log(f"-> Sending END packet (Attempt {attempt+1})", "status")
                        
                        self.expected_ack_seq = seq_num
                        self.ack_received_event.clear()
                        
                        self.ethernet_transmitter.transmit(target, MY_ADDRESS, end_payload)
                        
                        if self.ack_received_event.wait(timeout=2.5):
                            end_success = True
                            break
                        else:
                            self.log(f"XX Endreply {seq_num} Timeout. Retransmitting...", "error")
                            
                    if end_success:
                        self.log(f"++ EFTP Transfer Complete to {target} ++", "received")
                    else:
                        self.log(f"XX EFTP Endreply Failed. Transfer status unknown.", "error")

                self.tx_queue.task_done()
                #Increase delay time from 15 to 35 tto ensure enqueued messages to not get muddled.
                if current_protocol == "Marconi (OOK)":
                   time.sleep(UNIT_TIME * 35)
                else:
                    time.sleep(UNIT_TIME * 15)  # Short delay after teletype transmission


    def transmit_marconi(self, target, msg):
        while self.channel_busy:
            time.sleep(random.uniform(0.5, 2.0))
            
        self.log(f"-> Keying {target}: {msg}")
        self.set_led("TX", "red")
        
        packet = f"{target}{MY_ADDRESS}{msg}"
        
        # 1. Build the mathematical envelope (1 = Tone, 0 = Silence)
        units = []
        for char in packet.upper():
            code = MORSE_DICT.get(char, "")
            if code == '/':
                units.extend([0] * 7) # Word gap
            else:
                for sym in code:
                    if sym == '.':
                        units.append(1)
                    elif sym == '-':
                        units.extend([1, 1, 1])
                    units.append(0) # Inter-symbol gap
                units.extend([0, 0]) # Complete the 3-unit inter-character gap
                
        # Pad the end with absolute silence (zeros) so the SDR cyclic buffer 
        # doesn't accidentally repeat the final tone while powering down!
        units.extend([0] * 10)

        # 2. Convert to a mathematically perfect, continuous Complex Waveform
        samples_per_unit = int(SAMP_RATE * UNIT_TIME)
        total_samples = len(units) * samples_per_unit
        
        t = np.arange(total_samples)
        carrier = 0.5 * (np.exp(1j * 2 * np.pi * 0.1 * t)) * 2**14
        
        envelope = np.zeros(total_samples)
        for i, u in enumerate(units):
            if u == 1:
                envelope[i*samples_per_unit : (i+1)*samples_per_unit] = 1.0
                
        rf_wave = carrier * envelope
        
        # 3. Play PC Audio in a background thread so it doesn't delay the perfect RF math
        threading.Thread(target=self._play_marconi_audio_sync, args=(packet,), daemon=True).start()
        
        # 4. Stream to the SDR Hardware in safe chunks (Bypassing Windows Timers entirely!)
        chunk_size = 131072
        for i in range(0, len(rf_wave), chunk_size):
            chunk = rf_wave[i:i+chunk_size]
            if len(chunk) < chunk_size:
                pad = np.zeros(chunk_size - len(chunk), dtype=np.complex128)
                chunk = np.concatenate((chunk, pad))
            self.sdr.tx(chunk)
            
        self.sdr.tx_destroy_buffer()
        self.set_led("TX", "gray")

    def _play_marconi_audio_sync(self, packet):
        """Plays the PC speaker audio using OS timers, safely separated from the SDR."""
        for char in packet.upper():
            code = MORSE_DICT.get(char, "")
            if code == '/':
                time.sleep(UNIT_TIME * 7)
            else:
                for sym in code:
                    dur = 1 if sym == '.' else 3
                    # Play PC Speaker audio
                    marconi_audio.spark_sound(dur, UNIT_TIME, self.audio_mode.get())
                    time.sleep(UNIT_TIME * dur) 
                    time.sleep(UNIT_TIME) # Inter-symbol gap
                time.sleep(UNIT_TIME * 2) # Remaining Inter-character gap



    def receiver_loop(self):
        """Master RX loop that routes data to the external decoders."""
        
        # Track the protocol so we only rebuild the hardware buffer when it changes
        self.last_protocol = self.protocol_var.get()
        
        while True:
            current_protocol = self.protocol_var.get()
            
            # =========================================================
            # DYNAMIC BUFFER SWITCHER
            # =========================================================
            if current_protocol != self.last_protocol:
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception:
                    pass
                
                # Marconi needs a tiny buffer for high-speed OS stopwatch timing
                if current_protocol == "Marconi (OOK)" or current_protocol == "ALOHAnet (OOK)":
                    self.sdr.rx_buffer_size = 500
                # Ethernet/Teletype need giant buffers so no array data is dropped
                else:
                    self.sdr.rx_buffer_size = 131072
                    
                self.last_protocol = current_protocol
            samples = self.sdr.rx()
            
            if self.is_transmitting:
                # We are blasting RF. Ignore the incoming math so we don't 
                # deafen our CPU trying to decode our own echo!
                self.channel_busy = False
                self.ethernet_decoder.receiving = False
                self.ethernet_decoder.buffer = []
                self.just_finished_tx = True 
                continue
            
            if self.just_finished_tx:
                # The exact millisecond TX finishes, destroy the hardware buffer
                # so we don't accidentally process the tail-end of the echo!
                self.just_finished_tx = False
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception:
                    pass
                continue # Skip to the next clean buffer
            # Subtracting the mean instantly removes the LO Leakage from the 
            # other SDR, dropping the noise floor back down to near-zero 
            # and completely eliminating the destructive phase beating!
            dc_blocked = samples - np.mean(samples)
            
            pwr = np.max(np.abs(dc_blocked))
            #Evaluate whether the channel is busy by comparing to the current slider value.
            self.channel_busy = (pwr > self.current_threshold)
            
            # Update power meter at ~20 FPS (every 0.05 seconds) to prevent GUI freezing
            current_time = time.time()
            if current_time - self.last_meter_update > 0.05:
                self.update_power_meter(pwr)
                self.last_meter_update = current_time

            # Only update the GUI if the state actually flipped
            if self.channel_busy != self.last_rx_state:
                self.last_rx_state = self.channel_busy
                self.set_led("RX", "green" if self.channel_busy else "gray")

            # Route to the appropriate external decoder object
            current_protocol = self.protocol_var.get()
            packet_data = None
            
            if current_protocol == "Marconi (OOK)":
                packet_data = self.marconi_decoder.process(self.channel_busy)
            elif current_protocol == "Teletype (FSK)":
                packet_data = self.teletype_decoder.process(samples, self.channel_busy)
            elif current_protocol == "Wireless Ethernet (CSMA/CA)":
                # Ethernet uses raw samples to calculate the Manchester transitions
                packet_data = self.ethernet_decoder.process(samples, self.channel_busy)
                
            # If either decoder finished assembling a packet, process it
            if packet_data:
                self.parse_fixed_packet(packet_data, current_protocol)

                # ==========================================
                # THE FIX: FLUSH THE SDR HARDWARE BUFFER
                # ==========================================
                # The Teletype DSP math freezes this thread for ~1 second. 
                # We must destroy the hardware buffer so the SDR doesn't 
                # feed us stale static for the start of the next packet!
                try:
                    self.sdr.rx_destroy_buffer()
                except Exception as e:
                    pass

    def parse_fixed_packet(self, data, protocol):
        """Standardized Parsing with Ethernet CRC and EFTP Assembly logic."""
        
        # Strip invisible Null characters generated by the flush pad
        data = data.rstrip('\x00')
        
        if len(data) >= (ADDR_LEN * 2):
            dest = data[:3]
            src = data[3:6]
            
            # ----------------------------------------------------
            # ETHERNET MODE: EFTP RECEIVER LOGIC
            # ----------------------------------------------------
            if protocol == "Wireless Ethernet (CSMA/CA)":
                if len(data) < 14: # 3 Dest + 3 Src + 8 CRC = 14 min
                    self.log(f"?? Runt Ethernet Packet: {data}", "error")
                    return
                    
                payload = data[6:-8]
                received_crc = data[-8:]
                
                # Verify the 32-bit Frame Check Sequence
                frame_to_check = f"{dest}{src}{payload}".encode()
                calculated_crc = f"{zlib.crc32(frame_to_check) & 0xFFFFFFFF:08x}"
                
                if received_crc != calculated_crc:
                    self.log(f"[CRC FAILED] Hardware dropped corrupted frame from {src}", "error")
                    return # Drop the packet!
                
                # ==========================================
                # SOFTWARE LAYER: EFTP DISASSEMBLY
                # ==========================================
                packet_type, seq_num, eftp_data = ethernet_protocol.parse_eftp_payload(payload)
                
                if packet_type is None:
                    self.log(f"?? Invalid EFTP Payload: {payload}", "error")
                    return
                    
                if dest == MY_ADDRESS:
                    # Initialize the hidden assembly buffer if it doesn't exist yet
                    if not hasattr(self, 'rx_buffer'):
                        self.rx_buffer = ""
                        self.expected_rx_seq = 0

                    if packet_type == 'D': # DATA PACKET
                        self.log(f"<- Sending ACK {seq_num} to {src}", "status")
                        
                        # Only append new data to the hidden buffer (drop duplicate retransmissions)
                        if seq_num == self.expected_rx_seq:
                            self.rx_buffer += eftp_data
                            self.expected_rx_seq += 1
                            
                        # Fire the ACK directly through the hardware
                        ack_payload = ethernet_protocol.build_eftp_payload('A', seq_num)
                        self.ethernet_transmitter.transmit(src, MY_ADDRESS, ack_payload)
                        
                    elif packet_type == 'E': # END PACKET
                        self.log(f"<- Sending Endreply {seq_num} to {src}", "status")
                        
                        # THE GRAND REVEAL: Print the fully assembled hidden buffer!
                        self.log(f"*** FROM {src} ***: {self.rx_buffer}", "received")
                        
                        # Reset the buffer for the next incoming message
                        self.rx_buffer = ""
                        self.expected_rx_seq = 0
                        
                        # Fire the Endreply directly through the hardware
                        reply_payload = ethernet_protocol.build_eftp_payload('R', seq_num)
                        self.ethernet_transmitter.transmit(src, MY_ADDRESS, reply_payload)
                        
                    elif packet_type == 'A' or packet_type == 'R': # ACK or ENDREPLY
                        if seq_num == getattr(self, 'expected_ack_seq', -1):
                            self.log(f"<< ACK/REPLY {seq_num} RECEIVED >>", "status")
                            # Trip the flag to unblock the tx_daemon!
                            self.ack_received_event.set() 
                            
                else:
                    # If sniffing, just print the metadata so the console isn't flooded
                    self.log(f"[Sniffed] {src}->{dest}: Type {packet_type} Seq {seq_num}", "sniffed")

            # ----------------------------------------------------
            # MARCONI / ALOHA MODE (No Checksums or Headers)
            # ----------------------------------------------------
            else:
                msg = data[6:]
                if dest == MY_ADDRESS:
                    self.log(f"*** FROM {src} ***: {msg}", "received")
                else:
                    self.log(f"[Sniffed] {src}->{dest}: {msg}", "sniffed")
        else:
            self.log(f"?? Runt Packet: {data}", "error")

if __name__ == "__main__":
    root = tk.Tk()
    app = MarconiNode(root)
    root.mainloop()