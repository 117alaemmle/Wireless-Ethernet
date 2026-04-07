import time

class MarconiDecoder:
    def __init__(self, unit_time, reverse_dict):
        self.unit_time = unit_time
        self.reverse_dict = reverse_dict
        
        self.stream = ""
        self.symbols = ""
        self.in_pulse = False
        
        # FIX: Use the CPU hardware clock
        self.p_start = time.perf_counter() 
        self.s_start = time.perf_counter()
        
        self.last_busy_time = 0 
        self.space_added = False 

    def process(self, channel_busy):
        completed_packet = None
        current_time = time.perf_counter() # FIX
        
        if channel_busy:
            if not self.in_pulse:
                self.in_pulse = True
                self.p_start = current_time
            self.last_busy_time = current_time 
        else:
            if self.in_pulse:
                if (current_time - self.last_busy_time) > 0.03:
                    dur = self.last_busy_time - self.p_start
                    self.symbols += "." if dur < (self.unit_time * 2.0) else "-"
                    self.s_start = self.last_busy_time #Start the silence timer when the signal drops, not when the 30ms hang time finishes.
                    #self.s_start = current_time
                    self.in_pulse = False
            else:
                s_dur = current_time - self.s_start
                
                # 1. Character End
                if s_dur > (self.unit_time * 2.5) and self.symbols:
                    self.stream += self.reverse_dict.get(self.symbols, "?")
                    self.symbols = ""
                    self.space_added = False 
                    
                # 2. Word Gap (Space)
                if s_dur > (self.unit_time * 5.5) and self.stream and not self.space_added:
                    self.stream += " "
                    self.space_added = True
                    
                # 3. Packet End
                if s_dur > (self.unit_time * 25) and self.stream:
                    completed_packet = self.stream
                    self.stream = ""
                    self.space_added = False 
                    
        return completed_packet