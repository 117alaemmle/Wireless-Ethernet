import time

class MarconiDecoder:
    def __init__(self, unit_time, reverse_dict):
        self.unit_time = unit_time
        self.reverse_dict = reverse_dict
        
        self.stream = ""
        self.symbols = ""
        self.in_pulse = False
        self.p_start = time.time()
        self.s_start = time.time()
        
        # New flag to prevent duplicate spaces during long silences
        self.space_added = False 
        

    def process(self, channel_busy):
        completed_packet = None
        
        if channel_busy:
            if not self.in_pulse:
                self.in_pulse = True
                self.p_start = time.time()
        else:
            if self.in_pulse:
                dur = time.time() - self.p_start
                # Change the dot/dash boundary from 1.8 to 2.0 for 20 WPM
                self.symbols += "." if dur < (self.unit_time * 2.0) else "-"
                #self.symbols += "." if dur < (self.unit_time * 1.8) else "-"
                self.s_start = time.time()
                self.in_pulse = False
            else:
                s_dur = time.time() - self.s_start
                
                # 1. Character End
                if s_dur > (self.unit_time * 2.5) and self.symbols:
                    self.stream += self.reverse_dict.get(self.symbols, "?")
                    self.symbols = ""
                    self.space_added = False # Reset the flag after a letter is finalized
                    
                # 2. Word Gap (Space)
                # If we cross 6 units of silence, and we have data, and we haven't added a space yet
                # Keep the character end at 2.5, but relax the word gap slightly for 20 WPM.                 #if s_dur > (self.unit_time * 6.0) and self.stream and not self.space_added:
                if s_dur > (self.unit_time * 5.5) and self.stream and not self.space_added:
                    self.stream += " "
                    self.space_added = True
                    
                # 3. Packet End (Long Silence), increased to 25 units for 20 WPM
                if s_dur > (self.unit_time * 25) and self.stream:
                    completed_packet = self.stream
                    self.stream = ""
                    self.space_added = False # Reset for the next packet
                    
        return completed_packet