import numpy as np
import adi
import matplotlib.pyplot as plt
import time

# --- 1. Configuration ---
URI = "ip:192.168.2.1"
FREQ = 433e6       # 433 MHz
SAMP_RATE = 1e6    # 1 MSPS

print("Connecting to ADALM-PLUTO...")
sdr = adi.Pluto(URI)
sdr.sample_rate = int(SAMP_RATE)

# Configure RX
sdr.rx_lo = int(FREQ)
sdr.rx_buffer_size = 1000
sdr.rx_hardwaregain_chan0 = 10  # Moderate receive gain

# Configure TX
sdr.tx_lo = int(FREQ)
sdr.tx_hardwaregain_chan0 = -20 # Low transmit gain for safety

# --- 2. Generate a Test Signal ---
# We will generate a 10 kHz sine wave. 
# Because it's offset from our center frequency (433 MHz), 
# it's easy to see and proves the radio is actually tuning and mixing.
print("Generating test signal...")
fs = sdr.sample_rate
fc = 10000  # 10 kHz offset
t = np.arange(1000) / fs
# Generate complex sine wave and scale it to fit the Pluto's 12-bit DAC
tx_signal = 0.5 * np.exp(1j * 2 * np.pi * fc * t) * (2**14)

# --- 3. Transmit and Receive ---
print("Transmitting signal cyclically...")
sdr.tx_cyclic_buffer = True # This keeps repeating the signal automatically
sdr.tx(tx_signal)

# Give the hardware a tiny fraction of a second to stabilize
time.sleep(0.5)

print("Receiving signal...")
rx_signal = sdr.rx()

# Stop transmitting
sdr.tx_destroy_buffer()
print("Transmission stopped.")

# --- 4. Plot the Results ---
# We will plot the first 200 samples of the Real (I) and Imaginary (Q) parts
plt.figure(figsize=(10, 5))
plt.plot(np.real(rx_signal[:200]), label='Real (I)')
plt.plot(np.imag(rx_signal[:200]), label='Imaginary (Q)')
plt.title("ADALM-PLUTO Hardware Loopback Test")
plt.xlabel("Sample Index")
plt.ylabel("Amplitude")
plt.legend()
plt.grid(True)
plt.show()