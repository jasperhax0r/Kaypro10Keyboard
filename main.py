from machine import Pin
import time

# ==========================================================
# MATRIX CONFIGURATION
# ==========================================================

ROW_PINS = [0, 1, 2, 3, 4, 5, 6, 7]
COL_PINS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]

DEBOUNCE_MS = 20
SCAN_DELAY_US = 50


KEYMAP = [
    ["A", "I", "Q", "Y", "7", "'", "CTRL", "LINEFEED", "3", "RETURN"],
    ["B", "J", "R", "Z", "8", "\\", "CAPS", "UP", "4", "-"],
    ["C", "K", "S", "1", "9", ",", "DEL", "DOWN", "5", "'"],
    ["D", "L", "T", "2", "0", ".", "BACKSPACE", "LEFT", "6", "]"],
    ["E", "M", "U", "3", "-", "/", "SPACE", "RIGHT", "7", None],
    ["F", "N", "V", "4", "=", "LSHIFT", "ESC", "0", "8", None],
    ["G", "O", "W", "5", "`", "RSHIFT", "TAB", "1", "9", None],
    ["H", "P", "X", "6", ";", "[", "RETURN", "2", ".", None],
]

# ==========================================================
# UART
# ==========================================================

from machine import UART

kaypro_uart = UART(
    1,
    baudrate=300,
    tx=Pin(20),
    rx=Pin(21)
)

# ==========================================================
# STATUS LED / CAPS LED / BUZZER
# ==========================================================

# Pico onboard LED
power_led = Pin("LED", Pin.OUT)
power_led.value(1)   # ON whenever keyboard powered

# Caps Lock LED
caps_led = Pin(26, Pin.OUT)
caps_led.value(0)

# Buzzer
buzzer = Pin(22, Pin.OUT)
buzzer.value(0)

# ==========================================================
# MODIFIER STATE
# ==========================================================

shift_active = False
ctrl_active = False
caps_lock = False


# ==========================================================
# SHIFT SYMBOL MAP
# ==========================================================

SHIFT_MAP = {
    "1": "!",
    "2": "@",
    "3": "#",
    "4": "$",
    "5": "%",
    "6": "^",
    "7": "&",
    "8": "*",
    "9": "(",
    "0": ")",

    "-": "_",
    "=": "+",
    "`": "~",

    "[": "{",
    "]": "}",

    ";": ":",
    "'": "\"",

    ",": "<",
    ".": ">",
    "/": "?",

    "\\": "|"
}

# ==========================================================
# GPIO SETUP
# ==========================================================

# Rows = outputs
rows = []
for pin_num in ROW_PINS:
    pin = Pin(pin_num, Pin.OUT)
    pin.value(1)  # idle HIGH
    rows.append(pin)

# Columns = inputs with pullups
cols = []
for pin_num in COL_PINS:
    pin = Pin(pin_num, Pin.IN, Pin.PULL_UP)
    cols.append(pin)

# ==========================================================
# STATE TRACKING
# ==========================================================

stable_keys = set()
candidate_keys = set()

last_change_time = time.ticks_ms()

# ==========================================================
# KEY PROCESSING
# ==========================================================

def send_key(key):

    global shift_active
    global ctrl_active
    global caps_lock

    # ----------------------------------
    # Ignore modifier keys themselves
    # ----------------------------------

    if key in ("LSHIFT", "RSHIFT", "CTRL", "CAPS"):
        return

    # ----------------------------------
    # Special keys
    # ----------------------------------

    special = {
        "RETURN": "\r",
        "LINEFEED": "\n",
        "BACKSPACE": "\b",
        "TAB": "\t",
        "ESC": chr(27),
        "SPACE": " ",
        "DEL": chr(127),
    }

    if key in special:
        kaypro_uart.write(special[key])
        print("TX:", repr(special[key]))
        return

    # ----------------------------------
    # CTRL handling
    # ----------------------------------

    if ctrl_active and len(key) == 1 and key.isalpha():

        ctrl_code = ord(key.upper()) - 64

        kaypro_uart.write(bytes([ctrl_code]))
        print("TX CTRL:", ctrl_code)

        return

    # ----------------------------------
    # Regular printable keys
    # ----------------------------------

    if len(key) == 1:

        char = key

        # alphabetic case handling
        if char.isalpha():

            uppercase = caps_lock ^ shift_active

            if uppercase:
                char = char.upper()
            else:
                char = char.lower()

        # shifted symbols
        else:
            if shift_active and char in SHIFT_MAP:
                char = SHIFT_MAP[char]

        kaypro_uart.write(char)
        print("TX:", char)
        

# ==========================================================
# BUZZER
# ==========================================================

def beep(duration_ms=40):

    buzzer.value(1)
    time.sleep_ms(duration_ms)
    buzzer.value(0)
    
# ==========================================================
# MATRIX SCAN
# ==========================================================

def scan_matrix():
    """
    Scan the matrix and return a set of pressed keys.

    Returns:
        {(row, col), ...}
    """

    detected = set()

    for row_index, row in enumerate(rows):

        # Activate row
        row.value(0)

        # allow signals to settle
        time.sleep_us(SCAN_DELAY_US)

        # read columns
        for col_index, col in enumerate(cols):

            if col.value() == 0:
                detected.add((row_index, col_index))

        # deactivate row
        row.value(1)

    return detected


# ==========================================================
# SOFTWARE 2KRO LOCKOUT
# ==========================================================

def apply_2kro_lockout(keys):
    """
    Diode-less ghost prevention.

    Allow:
        0, 1, or 2 simultaneous keys

    Reject:
        3+ simultaneous keys
    """

    if len(keys) <= 2:
        return keys

    return set()


# ==========================================================
# DEBOUNCE
# ==========================================================

def update_debounce(raw_keys):

    global candidate_keys
    global stable_keys
    global last_change_time

    now = time.ticks_ms()

    # State changed
    if raw_keys != candidate_keys:
        candidate_keys = raw_keys
        last_change_time = now
        return stable_keys

    # Stable long enough?
    elapsed = time.ticks_diff(now, last_change_time)

    if elapsed >= DEBOUNCE_MS:
        stable_keys = candidate_keys

    return stable_keys


# ==========================================================
# MAIN LOOP
# ==========================================================

print("Keyboard scanner ready")

previous_keys = set()

while True:

    # Scan hardware
    raw_keys = scan_matrix()

    # Apply ghost prevention
    filtered_keys = apply_2kro_lockout(raw_keys)

    # Debounce
    current_keys = update_debounce(filtered_keys)

    # Detect changes
    new_keys = current_keys - previous_keys
    released_keys = previous_keys - current_keys

    # --------------------------------------------------
    # Handle key presses
    # --------------------------------------------------

    for row, col in sorted(new_keys):

        key = KEYMAP[row][col]

        if key is None:
            continue

        # SHIFT
        if key in ("LSHIFT", "RSHIFT"):
            shift_active = True
            continue

        # CTRL
        if key == "CTRL":
            ctrl_active = True
            continue

        # CAPS LOCK
        if key == "CAPS":
            caps_lock = not caps_lock

            # Update LED
            caps_led.value(caps_lock)

            print("CAPS:", caps_lock)

            beep(20)

            continue

        print("PRESS   {}".format(key))

        # Optional key click
        beep(5)

        send_key(key)

    # --------------------------------------------------
    # Handle key releases
    # --------------------------------------------------

    for row, col in sorted(released_keys):

        key = KEYMAP[row][col]

        if key is None:
            continue

        print("RELEASE {}".format(key))

        if key in ("LSHIFT", "RSHIFT"):
            shift_active = False

        elif key == "CTRL":
            ctrl_active = False

    previous_keys = current_keys

    time.sleep_ms(1)