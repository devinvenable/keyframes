#!/usr/bin/env python3
"""Generate 12 brain-surgery stills for Slow and Easy (task 286).

Adapted from generate-insect-war.py; Gemini color masters are graded locally
with midi:I48. Run with no arguments for all images, or indexes 1..12 to resume
a subset. Existing masters and grades are never regenerated or overwritten.
An interrupted decode can recover from the saved response without an API call.

Outputs (outside the worktree, retained for Devin's keep/drop curation):
  /home/devin/src/2026/midi/generated/brain-surgery/respNN.json
  /home/devin/src/2026/midi/generated/brain-surgery/brain_surgery_NN.png
  /home/devin/src/2026/midi/generated/brain-surgery/brain_surgery_NN_bw.png
"""

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

OUT = Path("/home/devin/src/2026/midi/generated/brain-surgery")
MODEL = "gemini-2.5-flash-image"
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
MAX_ATTEMPTS = 4

NO_TEXT = ("No readable text anywhere in the image; any labels, panel markings "
           "or signage are illegible pseudo-English glyphs. No captions or watermark.")
STYLE = (
    "A single photorealistic cinematic color film still from a fictional 1950s "
    "clinical science-horror film, landscape composition. Period medical theater, "
    "practical sets and believable physical props, natural film lighting, aged "
    "chrome, enamel, glass and cotton. Uncanny clinical atmosphere and restrained "
    "period horror, no splattering blood or contemporary gore realism. "
)

PROMPTS = [
    STYLE + "Wide establishing shot from the back row of a steep surgical "
    "amphitheater. Masked surgeons in cotton gowns gather around an adult "
    "patient under drapes, a small exposed brain visible at the center of a "
    "stereotactic metal halo. Students watch from dark wooden galleries. "
    "A huge circular surgical lamp hangs over the tiny illuminated operating "
    "field; dusty shafts of window light cut across the room. " + NO_TEXT,

    STYLE + "Extreme macro side view of a vintage hand-cranked trepanation "
    "drill touching the ivory surface of a dry anatomical skull clamped in a "
    "brass teaching jig. The drill crown and a neat circular opening dominate "
    "the frame, intricate machining in sharp focus; a gloved hand and masked "
    "surgeon dissolve into shallow-focus darkness behind. " + NO_TEXT,

    STYLE + "Perfectly overhead view of a symmetrical operating table and "
    "four masked surgeons, their gloved hands around an exposed brain within "
    "a period anatomical head model. Radial chrome instrument trays and "
    "round surgical lamps form a strange mechanical flower. Cream tile floor, "
    "deep pools of shadow, precise restrained surgical tableau. " + NO_TEXT,

    STYLE + "Low eye-level still life on a laboratory shelf: three heavy "
    "glass specimen jars containing pale preserved human brains in amber "
    "fluid, one whole brain large in the foreground, smaller specimens "
    "receding into shadow. Rippling glass distortions, condensation, "
    "bakelite lids, blank aged labels, a cold window reflected in the jars. "
    + NO_TEXT,

    STYLE + "Medium close shot of a masked surgeon in round wire spectacles "
    "leaning over an exposed brain on an enamel dissection tray. A fantastic "
    "retro-futuristic instrument combines a jeweler's drill, articulated "
    "chrome arms and vacuum tubes. The surgeon adjusts a tiny probe with "
    "forceps, face lit by the warm tubes; a nurse watches from the shadows. "
    + NO_TEXT,

    STYLE + "Side-on anatomical cross-section tableau: a life-size teaching "
    "model of an adult human head split down its sagittal plane on a steel "
    "pedestal, revealing the folded brain, cerebellum and brain stem. Behind "
    "it, a dissecting microscope and a ghostly surgeon silhouette. Physical "
    "wax-and-resin medical museum realism, raking light across layered tissue "
    "textures, no diagram arrows. " + NO_TEXT,

    STYLE + "Hallucinatory microscopic-magnified view of folded neural tissue "
    "as a vast labyrinth. Brain convolutions fill the frame like soft pale "
    "mountain ridges, fine branching fibers stretching between them; tiny "
    "chrome electrodes and glass capillaries suggest an impossible surgical "
    "expedition through the tissue. Shallow focus and transmitted laboratory "
    "light, tactile practical miniature photography. " + NO_TEXT,

    STYLE + "Three-quarter close-up of an isolated exposed brain mounted in "
    "an open mechanical cranium on a laboratory bench. Delicate copper coils "
    "and fine chrome gears are grafted into one hemisphere, the other retains "
    "natural anatomical folds. Glass tubes and cloth-wrapped wires run to "
    "a vintage vacuum-tube apparatus; an adult surgeon's gloved fingers "
    "carefully hold a probe at the junction. " + NO_TEXT,

    STYLE + "Dramatic low-angle view from the head of an operating table: "
    "three enormous circular surgical lamps loom like moons above masked "
    "surgeons bending inward. At the lower edge, a trepanation brace and "
    "the curved rim of an anatomical skull model establish the brain "
    "surgery setting. Severe foreshortening, lamp glare, deep shadows, "
    "sterile drapes framing the image. " + NO_TEXT,

    STYLE + "Oblique close-up of a period vivisection demonstration staged "
    "with a preserved brain on a white enamel tray: hemispheres gently "
    "separated to reveal the inner structures, fine probes held by gloved "
    "hands, a curved scalpel and forceps arranged beside it. Dry restrained "
    "anatomical specimen detail, wet enamel highlights, no active bleeding. "
    "A dissecting microscope casts a long shadow across the bench. " + NO_TEXT,

    STYLE + "Wide deserted operating theater after an uncanny experiment. "
    "A lone brain in a glass bell jar occupies the operating table beneath "
    "a suspended ring of chrome drill arms. Coiled cables trail over the "
    "checkerboard floor toward banks of vacuum tubes; abandoned cotton "
    "gowns hang beside the door. Night outside tall frosted windows, "
    "a single work lamp illuminating the specimen. " + NO_TEXT,

    STYLE + "Tight diagonal composition of a skull teaching specimen in a "
    "stereotactic frame, several clean circular trepanation holes crossing "
    "the crown. Through one opening, pale brain folds are visible. A "
    "heavy vintage drill rests in the near foreground, out of focus, "
    "while a surgeon's magnifying lens enlarges one opening and distorts "
    "its edges. Chilly dawn light, tactile bone and tarnished steel. " + NO_TEXT,
]

GRADE = ("hue=s=0,curves=master='0/0.04 0.25/0.22 0.5/0.52 0.75/0.8 1/0.97',"
         "gblur=sigma=0.6,noise=alls=14:allf=t+u,"
         "vignette=PI/5.5:mode=backward:dither=1")


def write_atomic(path, data):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def extract_image(response):
    for candidate in response.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline:
                data = base64.b64decode(inline["data"], validate=True)
                if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise RuntimeError("Expected a PNG image; raw response retained")
                return data
    return None


def generate(index, prompt):
    master = OUT / f"brain_surgery_{index:02d}.png"
    if master.exists():
        return master
    response_path = OUT / f"resp{index:02d}.json"
    if response_path.exists():
        image = extract_image(json.loads(response_path.read_bytes()))
        if image:
            write_atomic(master, image)
            return master

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is required for missing images")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    request = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "x-goog-api-key": key,
    })
    for attempt in range(1, MAX_ATTEMPTS + 1):
        with urllib.request.urlopen(request, timeout=180) as result:
            raw = result.read()
        write_atomic(response_path, raw)
        response = json.loads(raw)
        image = extract_image(response)
        if image:
            write_atomic(master, image)
            return master
        reasons = [c.get("finishReason") for c in response.get("candidates", [])]
        if reasons != ["NO_IMAGE"]:
            raise RuntimeError(f"No image; finish reasons {reasons}; see {response_path.name}")
        if attempt < MAX_ATTEMPTS:
            print(f"[{index:02d}] NO_IMAGE; retrying unchanged ({attempt + 1}/{MAX_ATTEMPTS})",
                  flush=True)
            time.sleep(2)
    raise RuntimeError(f"NO_IMAGE after {MAX_ATTEMPTS} attempts; rerun index {index}")


def grade(master):
    output = master.with_name(master.stem + "_bw.png")
    if not output.exists():
        temporary = output.with_name(output.stem + ".tmp.png")
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error", "-i", str(master),
            "-vf", GRADE, "-frames:v", "1", str(temporary),
        ], check=True)
        temporary.replace(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("indexes", metavar="INDEX", type=int, nargs="*",
                        help="Optional indexes 1..12; existing outputs are preserved")
    args = parser.parse_args()
    if any(i < 1 or i > len(PROMPTS) for i in args.indexes):
        parser.error("indexes must be between 1 and 12")
    indexes = list(dict.fromkeys(args.indexes)) or range(1, len(PROMPTS) + 1)
    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    for index in indexes:
        print(f"[{index:02d}] Checking master and grade", flush=True)
        try:
            master = generate(index, PROMPTS[index - 1])
            bw = grade(master)
            print(f"[{index:02d}] OK {master.name} {bw.name}", flush=True)
        except Exception as error:
            failures.append(index)
            print(f"[{index:02d}] FAIL {error}", file=sys.stderr, flush=True)
    if failures:
        print("Retry indexes: " + " ".join(map(str, failures)), file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
