import threading
import winsound # Note: Standard on Windows. Use a placeholder for other OS.

# Frequency profiles
FREQS = {
    "Marconi": 120,
    "Cinema": 600,
    "Silent": None
}

def beep_worker(mode, duration_ms):
    """Executes the beep in a background thread."""
    freq = FREQS.get(mode)
    if freq:
        winsound.Beep(freq, max(1, duration_ms))

def spark_sound(duration_units, unit_time, mode):
    """
    Interface for the main GUI. 
    Prevents audio latency from blocking SDR buffers[cite: 521, 746].
    """
    if mode == "Silent":
        return
        
    ms = int(unit_time * duration_units * 1000)
    threading.Thread(target=beep_worker, args=(mode, ms), daemon=True).start()