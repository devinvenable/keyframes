#!/usr/bin/env python3
"""Edit an image with gemini-2.5-flash-image: input image + instruction -> new image.

Usage: gemini_edit.py --input SRC.png --output OUT.png --prompt "..."
Surgical edits (place on a wall, swap background) that local img2img can't do.
"""
import argparse, base64, json, mimetypes, os, sys, urllib.request

MODEL = "gemini-2.5-flash-image"
KEY = os.environ["GEMINI_API_KEY"]
URL = (f"https://generativelanguage.googleapis.com/v1beta/models/"
       f"{MODEL}:generateContent?key={KEY}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--prompt", required=True)
    a = ap.parse_args()

    mime = mimetypes.guess_type(a.input)[0] or "image/png"
    with open(a.input, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    body = json.dumps({
        "contents": [{"parts": [
            {"text": a.prompt},
            {"inlineData": {"mimeType": mime, "data": data}},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
    for part in resp["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            with open(a.output, "wb") as f:
                f.write(base64.b64decode(inline["data"]))
            print(f"wrote {a.output}")
            return 0
    print("no image part in response", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
