# =====================================================================
# test_voice.py - Cong cu test nhan dien giong noi TRUC TIEP (khong can
# chay toan bo tro ly). Noi vao micro, xem Vosk chep lai thanh chu gi,
# va parser hieu lenh nao. Ctrl+C de thoat.
#
# Cach dung (trong venv):
#   python test_voice.py            # dung micro mac dinh cua Windows
#   python test_voice.py --list     # liet ke cac micro de chon device_index
#   python test_voice.py --device 3 # dung micro co chi muc 3
# =====================================================================
from __future__ import annotations

import argparse
import json
import queue
import sys

import yaml


def main():
    ap = argparse.ArgumentParser(description="Test Vosk + parser lenh giong noi")
    ap.add_argument("--list", action="store_true", help="Liet ke thiet bi am thanh roi thoat")
    ap.add_argument("--device", type=int, default=None, help="Chi muc micro (xem --list)")
    args = ap.parse_args()

    import sounddevice as sd

    if args.list:
        print(sd.query_devices())
        print("\nMac dinh hien tai:", sd.default.device)
        return

    with open("config.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Cho phep ghi de device_index bang tham so dong lenh.
    if args.device is not None:
        config.setdefault("voice", {})["device_index"] = args.device

    from core.voice_engine import VoiceEngine

    ve = VoiceEngine(config, queue.Queue())
    import vosk

    vosk.SetLogLevel(-1)
    print(f"Model: {ve.model_path}")
    print(f"Wake word: {', '.join(ve.wake_words)}")
    print("Dang tai model...")
    model = vosk.Model(ve.model_path)
    rec = vosk.KaldiRecognizer(model, ve.sample_rate)

    audio_q: "queue.Queue[bytes]" = queue.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[canh bao micro] {status}", file=sys.stderr)
        audio_q.put(bytes(indata))

    device = ve.cfg.get("device_index", -1)
    device = None if device is None or int(device) < 0 else int(device)
    dev_name = sd.query_devices(device if device is not None else sd.default.device[0])["name"]
    print(f"Micro: {dev_name}")
    print("=" * 60)
    print("Noi thu: 'tìm kiếm thời tiết', 'mở youtube', 'dán'...")
    print("Ctrl+C de thoat.")
    print("=" * 60)

    try:
        with sd.RawInputStream(samplerate=ve.sample_rate, blocksize=8000,
                               device=device, dtype="int16", channels=1,
                               callback=callback):
            while True:
                data = audio_q.get()
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "").strip()
                    if not text:
                        continue
                    print(f"\n[NGHE DUOC] {text}")
                    events = ve.parse_command(text)
                    if events:
                        for ev in events:
                            print(f"  -> LENH: {ev.name} {ev.payload}")
                    else:
                        print("  -> (khong hieu / bo qua)")
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                    if partial:
                        print(f"\r... {partial}   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nDa dung test.")


if __name__ == "__main__":
    main()
