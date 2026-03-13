import sounddevice as sd
import numpy as np
import time

def check_signal(device_id, duration=5):
    print(f"Checking signal on device {device_id} for {duration} seconds...")
    try:
        dev_info = sd.query_devices(device_id, 'input')
        rate = int(dev_info['default_samplerate'])
        print(f"Device: {dev_info['name']} (Native Rate: {rate})")
        
        levels = []
        def callback(indata, frames, time, status):
            if status: print(f"Status: {status}")
            rms = np.sqrt(np.mean(indata**2))
            levels.append(rms)
        
        with sd.InputStream(device=device_id, channels=1, samplerate=rate, callback=callback):
            time.sleep(duration)
        
        if levels:
            max_lvl = max(levels)
            avg_lvl = sum(levels) / len(levels)
            print(f"Max Amplitude: {max_lvl:.6f}")
            print(f"Avg Amplitude: {avg_lvl:.6f}")
            if max_lvl < 0.001:
                print("VERDICT: SILENT. The device is open but receiving no audio.")
            else:
                print("VERDICT: ACTIVE. Audio signal detected.")
        else:
            print("VERDICT: NO DATA RECEIVED.")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test Mic (default) and Stereo Mix (23)
    print("--- MIC TEST ---")
    check_signal(None, 3) 
    print("\n--- STEREO MIX TEST (ID 23) ---")
    check_signal(23, 5)
