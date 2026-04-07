import time

class MarconiDecoder:
    def __init__(self, unit_time, reverse_dict):
        self.unit_time = unit_time
        self.reverse_dict = reverse_dict
        
        # Internal state variables
        self.stream = ""
        self.symbols = ""
        self.in_pulse = False
        self.p_start = time.time()
        self.s_start = time.time()

    def process(self, channel_busy):
        """Processes the channel state and returns a packet string if complete."""
        completed_packet = None
        
        if channel_busy:
            if not self.in_pulse:
                self.in_pulse = True
                self.p_start = time.time()
        else:
            if self.in_pulse:
                dur = time.time() - self.p_start
                self.symbols += "." if dur < (self.unit_time * 1.8) else "-"
                self.s_start = time.time()
                self.in_pulse = False
            else:
                s_dur = time.time() - self.s_start
                
                # Character End
                if s_dur > (self.unit_time * 2.5) and self.symbols:
                    self.stream += self.reverse_dict.get(self.symbols, "?")
                    self.symbols = ""
                    
                # Packet End (Long Silence)
                if s_dur > (self.unit_time * 12) and self.stream:
                    completed_packet = self.stream
                    self.stream = ""
                    
        return completed_packet