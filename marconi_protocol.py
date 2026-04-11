# marconi_protocol.py

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
    '@': '.--.-.',   # At Sign 
    '(': '-.--.',    # Open Parenthesis
    ')': '-.--.-',   # Close Parenthesis
    ':': '---...',   # Colon
    ';': '-.-.-.',   # Semicolon
    '=': '-...-',    # Double Dash / Equals
    '+': '.-.-.',    # Plus
    '"': '.-..-.',   # Quotation Mark
    "'": '.----.',   # Apostrophe
    
    # Our software-specific word gap trigger
    ' ': '/'         
}

REVERSE_DICT = {v: k for k, v in MORSE_DICT.items() if v != '/'}