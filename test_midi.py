import time
import mido

START_NOTE = 36
END_NOTE = 99
VELOCITY = 64    # Adjust velocity if needed
DELAY = 0.1      # Time in seconds between notes

def main():
    # Create a virtual MIDI output port. 
    # On macOS and Linux, this will create a virtual port you can pick up in other programs.
    # On Windows, you might need a virtual MIDI driver (like LoopMIDI).
    with mido.open_output('Virtual Keyboard', virtual=True) as outport:
        print("Virtual keyboard running. Connect to 'Virtual Keyboard' to receive notes.")
        print("Press Ctrl+C to stop.")

        while True:
            # Cycle through the note range
            for note in range(START_NOTE, END_NOTE + 1):
                # Send a note_on message
                outport.send(mido.Message('note_on', note=note, velocity=VELOCITY))
                time.sleep(DELAY)
                # Send a note_off message
                outport.send(mido.Message('note_off', note=note, velocity=0))
                
                # Optional: A brief pause before next note
                # (Currently DELAY is between note_on and note_off, 
                # so to have a pause after note_off, add another sleep here if desired)
                # time.sleep(DELAY * 0.5) # For example
                
            # Once we reach the end, loop back to the start

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped by user.")
