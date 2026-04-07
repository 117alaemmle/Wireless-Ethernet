import threading
import time

# Marconi's 'Spark' was typically a low, 120Hz growl
MARCONI_PITCH = 120 

def beep_worker(duration_ms):
    """The actual worker that talks to the PC hardware."""
    try:
        import winsound
        winsound.Beep(MARCONI_PITCH, max(1, duration_ms))
    except ImportError:
        # Fallback for Linux/Mac
        print("\a", end="", flush=True)

def spark_sound(duration_units, unit_time):
    """
    Called by the main script. 
    Starts a thread so the audio doesn't block the SDR timing.
    """
    ms = int(unit_time * duration_units * 1000)
    threading.Thread(target=beep_worker, args=(ms,), daemon=True).start()