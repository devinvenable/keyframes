#!/usr/bin/env python3
"""Generate brain-surgery stills for Slow and Easy (tasks 286 and 291).

Adapted from generate-insect-war.py; Gemini color masters are graded locally
with midi:I48. Run with no arguments for keepers 02/04/06/07/09/10 and batch 2
(13..20), or explicit indexes 1..20 to resume a subset. The default excludes
discarded batch-1 indexes. Existing masters and grades are never overwritten.
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

# Batch 1 above is retained as provenance. All new prompts follow Devin's
# documentary-realism curation rules (midi:I77), superseding its sci-fi brief.
BATCH2_STYLE = (
    "A single believable color frame from a 1950s medical documentary or an old "
    "medical movie, landscape composition. Purely period-medical, photographed "
    "physical specimens and teaching props with ordinary practical lighting. "
    "Asymmetric off-center composition, imperfect incidental framing and "
    "documentary plainness; no perfect symmetry, no circular balanced "
    "composition, no over-polished rendering or AI-art aesthetic. Restrained "
    "faded old-movie color, modest grain, natural shadows and worn materials. "
    "ABSOLUTELY NO cyber-futurism, gears, mechanical grafts, machine-anatomy "
    "hybrids, futuristic equipment or fantastical anatomy. No active bleeding "
    "or splattering gore. "
)

PROMPTS += [
    BATCH2_STYLE + "Tight side close-up of a worn wax teaching model of a human "
    "brain cut along its sagittal plane. The cut face, corpus callosum, "
    "cerebellum and brain stem occupy nearly the entire frame, the upper edge "
    "incidentally cropped. Slightly chipped painted wax and ordinary handling "
    "marks. A plain matte warm-gray wall is the only background; no laboratory "
    "clutter, stands, instruments, diagram arrows or people. Soft window light "
    "from one side, faded amber and muted pink old-film color. " + NO_TEXT,

    BATCH2_STYLE + "Very close oblique view of a coronal cross-section brain "
    "teaching model lying on a plain cream cloth. One physical cut slice fills "
    "the frame with its ventricles and layered hand-painted wax surfaces; its "
    "left edge falls outside the photograph. Camera slightly to one side, "
    "never a centered frontal diagram. Only a narrow strip of unadorned cloth "
    "behind it; no instruments, display furniture or other objects. Plain "
    "tungsten room light and faded warm old-movie color. " + NO_TEXT,

    BATCH2_STYLE + "Close-up insert shot of the lower cutaway portion of a "
    "life-size plaster-and-wax brain teaching model, emphasizing the cerebellum "
    "and brain stem beneath the cut cerebral hemisphere. An oblique side "
    "angle with the upper cerebrum cropped out naturally. Dull hand-painted "
    "surfaces, small scuffs and believable physical scale. Plain out-of-focus "
    "olive-gray background with nothing else visible, no skull, no tools, no "
    "surgeons. Uneven daylight, restrained faded cream and russet colors. "
    + NO_TEXT,

    BATCH2_STYLE + "Tight three-quarter close-up of a detachable wax brain "
    "teaching model resting on a bare dull enamel surface. A single removable "
    "section has been lifted away to expose the interior beside the remaining "
    "folded hemisphere; the removed piece is outside the picture. Brain "
    "fills most of the frame and sits off-center, seen from a casually chosen "
    "slightly elevated angle. Minimal plain charcoal background, no additional "
    "props or display case. Modest focus falloff, worn wax with muted "
    "ochre-pink old-movie color, not a glossy medical illustration. " + NO_TEXT,

    BATCH2_STYLE + "Candid eye-level close view of a single heavy rectangular "
    "glass specimen jar holding a preserved human brain in pale amber fluid "
    "on a scuffed laboratory shelf. Jar sits off-center, its lid partly "
    "cropped; the edge of another jar intrudes softly at one side. Uneven "
    "glass, small bubbles, mild liquid distortion and a blank paper label. "
    "Bare dim wall behind, no elaborate apparatus. Weak afternoon window "
    "light and faded honey-brown old-movie color. " + NO_TEXT,

    BATCH2_STYLE + "An unposed medium-close documentary view of a period "
    "laboratory assistant in a plain cotton coat holding a sealed brain "
    "specimen jar at bench height with both hands. Only the torso and hands "
    "are in frame; the face is above the crop. The pale brain is visibly "
    "suspended in preserving fluid behind thick glass. A bare worn wooden "
    "bench and simple plaster wall, no other equipment. Slightly tilted "
    "casual framing, muted greenish shadows and warm faded film highlights. "
    + NO_TEXT,

    BATCH2_STYLE + "Over-the-shoulder documentary insert of a medical lecturer "
    "demonstrating a preserved human brain on a shallow white enamel tray. "
    "One gloved hand steadies the specimen while a simple wooden pointer "
    "indicates a natural fold. Cotton sleeve enters from one edge, lecturer's "
    "body mostly outside frame. Side angle, tray runs diagonally and is "
    "partly cropped, plain dark bench with no arranged ring of instruments. "
    "Quiet workaday anatomy lesson, soft window light, faded brown and cream "
    "old-film colors. " + NO_TEXT,

    BATCH2_STYLE + "A candid medium shot taken from the side of a 1950s "
    "anatomy laboratory doorway. A seated doctor in cotton gown and round "
    "spectacles examines a brain specimen in a plain glass jar on a small "
    "wooden worktable. Doctor is absorbed in work rather than posing; the "
    "doorjamb partly obscures one edge and the composition is uneven. One "
    "frosted window, bare plaster wall, no theatrical surgical lamps or "
    "machinery. Soft overcast light, subdued amber highlights and faded "
    "olive shadows like an ordinary old color movie. " + NO_TEXT,
]

DEFAULT_INDEXES = (2, 4, 6, 7, 9, 10, *range(13, 21))

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
                        help="Optional indexes 1..20; defaults to keepers and batch 2")
    args = parser.parse_args()
    if any(i < 1 or i > len(PROMPTS) for i in args.indexes):
        parser.error(f"indexes must be between 1 and {len(PROMPTS)}")
    indexes = list(dict.fromkeys(args.indexes)) or DEFAULT_INDEXES
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
