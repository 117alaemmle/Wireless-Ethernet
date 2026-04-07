import os
import time
import random
import threading
import queue
import tkinter as tk
from tkinter import scrolledtext
import numpy as np  #pip install numpy pyadi-iio
import adi
#import marconiAudio
import marconiAudio
from tkinter import ttk  # Required for the Combobox
import teletype_protocol # New module to handle teletype.
import marconi_audio #Play audio tone through PC speakers
import marconi_rx
import teletype_rx, teletype_tx


# --- Configuration ---
MY_ADDRESS = "001"
URI = "ip:192.168.2.1"
FREQ = 433e6
SAMP_RATE = 1e6
#UNIT_TIME = 0.12  # Solid reliability #10 Words Per Minute for Marconi, a beginner speed.
UNIT_TIME = 0.06 # 20 Words per minute, a professional operator's standard speed in ~1912. 
#A professional Marconi operator in the early 1900s (like the operators on the Titanic) typically cruised at 15 to 20 WPM. Their speed was physically limited by the massive, heavy brass telegraph keys used to switch the high-voltage spark-gap equipment.
#By World War II, operators using smaller keys or semi-automatic "bugs" (which used a vibrating pendulum to generate dots automatically) could comfortably send at 25 to 30 WPM, with elite operators pushing 40+ WPM.
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
            self.sdr.rx_buffer_size = 500
        except Exception as e:
            print(f"Hardware Error: {e}")
            
        # --- THE QUEUE ---
        # This stores (target, message) tuples
        self.tx_queue = queue.Queue()

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

        # --- THE LIVE THRESHOLD FIX ---
        self.current_threshold = 500.0 # Instance variable replaces the global THRESHOLD
        
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
            values=["Marconi (OOK)", "Teletype (FSK)"],
            state="readonly"
        )
        self.protocol_dropdown.pack(padx=10, pady=5, side="left")

        self.channel_busy = False
        self.last_rx_state = False  # Tracks previous state to prevent UI flooding

        # --- Marconi (OOK) Receiver State ---
        self.m_stream = ""
        self.m_symbols = ""
        self.m_in_pulse = False
        self.m_p_start = time.time()
        self.m_s_start = time.time()

        # Initialize Decoders for decoding incoming messages
        self.marconi_decoder = marconi_rx.MarconiDecoder(UNIT_TIME, REVERSE_DICT)
        self.teletype_decoder = teletype_rx.TeletypeDecoder(SAMP_RATE)

        # Initialize Transmitters
        self.teletype_transmitter = teletype_tx.TeletypeTransmitter(
            self.sdr, SAMP_RATE, self.log, self.set_led
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



    def log(self, message):
        def append():
            ts = time.strftime("[%H:%M:%S]")
            self.history.configure(state='normal')
            self.history.insert(tk.END, f"{ts} {message}\n")
            self.history.configure(state='disabled')
            self.history.see(tk.END)
        self.root.after(0, append)

    ###################################
    # Play Tone sends the RF signal and audio through PC speakers
    ###################################

    def play_tone(self, duration_units):
        """Sends RF via Pluto and calls the external Marconi audio script."""
        num_samples = int(SAMP_RATE * UNIT_TIME * duration_units)
        t = np.arange(num_samples)
        
        #Turn on TX LED while transmitting
        self.set_led("TX", "red")

        # 1. Generate RF carrier
        samples = 0.5 * (np.exp(1j * 2 * np.pi * 0.1 * t)) * 2**14
        
        # 2. Call the external Marconi sound function
        #marconiAudio.spark_sound(duration_units, UNIT_TIME)
        marconi_audio.spark_sound(duration_units, UNIT_TIME, self.audio_mode.get())
        
        # 3. Transmit via ADALM-PLUTO
        self.sdr.tx(samples)
        time.sleep(UNIT_TIME * duration_units)
        self.sdr.tx_destroy_buffer()

        # Turn TX Light back to Gray
        self.set_led("TX", "gray")

    # Set LED colors in a thread-safe manner depending on the action taken by the code
    def set_led(self, led_type, color):
        """Thread-safe method to change LED colors."""
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
                
                while self.channel_busy:
                    time.sleep(random.uniform(0.5, 2.0))
                
                # Check which protocol the user has selected
                current_protocol = self.protocol_var.get()
                
                if current_protocol == "Marconi (OOK)":
                    self.transmit_marconi(target, msg)
                elif current_protocol == "Teletype (FSK)":
                    self.teletype_transmitter.transmit(target, MY_ADDRESS, msg)     

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
        
        # HEADER: [RECIPIENT][SENDER] [MESSAGE]
        # No spaces required between addresses!
        packet = f"{target}{MY_ADDRESS}{msg}"
        
        for char in packet.upper():
            code = MORSE_DICT.get(char, "")
            # THE FIX: Catch the space character and output silence
            if code == '/':
                time.sleep(UNIT_TIME * 7) # Standard 7-unit word gap
            else:
                for sym in code:
                    self.play_tone(1 if sym == '.' else 3)
                    time.sleep(UNIT_TIME) # Inter-symbol gap
                time.sleep(UNIT_TIME * 3) # Inter-character gap


    def receiver_loop(self):
        """Master RX loop that routes data to the external decoders."""
        while True:
            samples = self.sdr.rx()
            pwr = np.max(np.abs(samples))
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
                
            # If either decoder finished assembling a packet, process it
            if packet_data:
                self.parse_fixed_packet(packet_data)

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

    def parse_fixed_packet(self, data):
        """Standardized 3-3-Rest Parsing."""
        if len(data) >= (ADDR_LEN * 2):
            dest = data[:3]
            src = data[3:6]
            msg = data[6:]
            
            if dest == MY_ADDRESS:
                self.log(f"*** FROM {src} ***: {msg}")
            else:
                self.log(f"[Sniffed] {src}->{dest}: {msg}")
        else:
            self.log(f"?? Runt Packet: {data}")

if __name__ == "__main__":
    root = tk.Tk()
    app = MarconiNode(root)
    root.mainloop()