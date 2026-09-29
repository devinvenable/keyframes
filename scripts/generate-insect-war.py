#!/usr/bin/env python3
"""Generate the insect-war image series (task 189).

Mechanical insect robots at war — photorealistic metallic machines based on
grasshoppers, mantises, beetles, ants; futuristic tech (2050-3050), with the
1950s film-still ethos delivered by local post-grade (never by regeneration).

Writes to /home/devin/src/2026/midi/generated/insect-war/:
  respNN.json           raw generateContent response
  insect_war_NN.png     decoded color master
  insect_war_NN_bw.png  1950s film-still grade (ffmpeg)
"""
import base64
import json
import os
import subprocess
import sys
import urllib.request

OUT = "/home/devin/src/2026/midi/generated/insect-war"
MODEL = "gemini-2.5-flash-image"
KEY = os.environ["GEMINI_API_KEY"]
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"

NO_TEXT = ("No readable text anywhere in the image; any panel markings, "
           "stencils or insignia are illegible pseudo-English glyphs.")

STYLE = ("Photorealistic cinematic still, natural film lighting, shallow "
         "grain, realistic materials: brushed steel, tarnished chrome, oily "
         "hydraulics, riveted armor plate. ")

PROMPTS = [
    # --- wide swarm / anthill-mountain shots ---
    STYLE + "Vast wide shot of a mountain that is entirely a writhing anthill "
    "of millions of mechanical insect robots — metallic ants and beetles "
    "swarming over each other in heaving piles, the whole slope alive and "
    "crawling like a magnified nest, smoke columns rising from battles on its "
    "flanks, tiny explosions glittering across the swarm, year 3050 war "
    "machines. " + NO_TEXT,

    STYLE + "Aerial wide shot of a battlefield plain where two colossal "
    "swarms of robotic insects collide like opposing armies — a tide of "
    "chrome grasshopper and locust machines leaping into a wall of black "
    "beetle tanks, dust and smoke, thousands of glinting metal bodies "
    "stretching to the horizon, futuristic 2050 warfare. " + NO_TEXT,

    STYLE + "Wide establishing shot at dusk: a towering termite-mound "
    "fortress built from interlocking mechanical insect bodies, its surface "
    "squirming with worm-like robotic larvae, siege swarms of winged "
    "mantis machines circling it while artillery beetles fire from ridges "
    "below, distant advanced technology of the year 3050. " + NO_TEXT,

    STYLE + "High wide shot of a cratered valley completely carpeted in "
    "wrecked and still-fighting mechanical insects — piles of severed "
    "chrome legs and antennae like windrows, fresh swarms pouring over the "
    "wreckage in glittering rivers, one enormous burning beetle war-machine "
    "collapsed in the center. " + NO_TEXT,

    # --- mid-range battle scenes ---
    STYLE + "Mid-range battle scene: a giant mechanical praying mantis war "
    "machine with scythe arms of polished steel locked in combat with an "
    "armored rhinoceros-beetle robot, sparks and hydraulic fluid spraying, "
    "smaller robotic ants swarming up both combatants' legs, muddy torn "
    "battlefield, smoke drifting through. " + NO_TEXT,

    STYLE + "Mid-range shot of chrome grasshopper mech-soldiers mid-leap "
    "over a trench, plasma-torch mouthparts glowing, while wasp-like "
    "aerial machines strafe from above; below, ant machines drag a wounded "
    "beetle robot apart, futuristic 2050 insect warfare. " + NO_TEXT,

    STYLE + "Mid-range battle scene in rain: a squad of mechanical army "
    "ants with riveted abdomens and glowing sensor eyes overwhelming a "
    "much larger stag-beetle war machine, climbing its armor plates and "
    "prying them open, steam and sparks, headlight-like eyes cutting "
    "through the downpour. " + NO_TEXT,

    STYLE + "Mid-range shot of a dragonfly gunship machine hovering low "
    "over burning wreckage, four transparent alloy wings blurring, its "
    "segmented tail articulated like chromed vertebrae, mantis infantry "
    "machines advancing beneath it through smoke, year 3050 technology. "
    + NO_TEXT,

    # --- close magnified / wormy / anatomical shots ---
    STYLE + "Extreme close-up as if through a microscope: a writhing mass "
    "of worm-like robotic larvae with segmented metal bodies, wet-looking "
    "oily surfaces, tiny grasping manipulators — and among the machinery, "
    "unsettling grafts of human anatomy: a realistic human hand emerging "
    "from a chrome segment, part of a human face set into an insect "
    "thorax, disturbing biomechanical detail. " + NO_TEXT,

    STYLE + "Macro close-up of a mechanical hornet's head, magnified like "
    "an electron microscope image but photoreal: compound eyes of hexagonal "
    "lenses, mandibles of machined titanium — and where its palps should "
    "be, small anatomically perfect human fingers; fine wormy cables pulse "
    "along its neck like veins. " + NO_TEXT,

    STYLE + "Close-up battlefield detail: the torn-open abdomen of a "
    "beetle war machine revealing an interior that is horrifyingly "
    "anatomical — human-like muscle fibers of red synthetic tissue woven "
    "through gears and pistons, a pale human torso fused into the "
    "machinery, robotic ants crawling into the wound, magnified wormy "
    "textures everywhere. " + NO_TEXT,

    STYLE + "Tight close-up of two small mechanical insects fighting on a "
    "single severed chrome limb: a silver mantis machine pinning a "
    "copper-bodied ant machine, both magnified so their surfaces show "
    "microscopic wormy ridges like machined skin, a tiny human eye set "
    "into the mantis's head staring at the lens. " + NO_TEXT,

    # === batch 2 (indexes 13-24, task 191) — new compositions ===
    # --- aerial dogfights ---
    STYLE + "Aerial dogfight high above a burning battlefield: a chrome "
    "dragonfly interceptor banking hard, wings a blur of transparent alloy, "
    "chased by three wasp fighter machines spitting glowing rounds, contrails "
    "and flak bursts scattered across a smoke-stained sky, wrecked winged "
    "machines tumbling toward the ground far below, year 3050 air war. "
    + NO_TEXT,

    STYLE + "Vertigo-inducing aerial shot looking straight down through a "
    "swirling dogfight of hundreds of winged insect machines — dragonflies, "
    "hornets and flying beetles spiraling in a vortex of glinting metal, "
    "tracer lines threading the swarm, the cratered battlefield miles "
    "below them like a scorched map, futuristic 2050 warfare. " + NO_TEXT,

    STYLE + "Close aerial shot at the moment of a mid-air collision: a "
    "titanium hornet fighter raking its barbed legs across the fuselage of "
    "a locust bomber machine, torn armor petals peeling back, hydraulic "
    "fluid streaming like blood in the slipstream, other winged machines "
    "dueling out of focus behind them. " + NO_TEXT,

    # --- night battles lit by tracer fire ---
    STYLE + "Night battle wide shot: a plain lit only by arcs of glowing "
    "tracer fire crisscrossing the dark, silhouetting thousands of "
    "mechanical ants and beetles advancing in waves, muzzle flashes "
    "strobing off wet chrome carapaces, a burning mantis war machine "
    "lighting one flank like a bonfire, year 3050 night warfare. " + NO_TEXT,

    STYLE + "Night scene in a ruined trench line: a mechanical praying "
    "mantis sentry lit from below by the green glow of its own plasma "
    "torch, tracer streams passing overhead, robotic ants with lamp-like "
    "eyes filing past in the dark, rain glittering in the weapon light, "
    "futuristic insect army at night. " + NO_TEXT,

    STYLE + "Night aerial bombardment: wasp machines diving out of a black "
    "sky marked by searchlight beams and streams of tracer fire, their "
    "steel abdomens releasing glowing bomblets over a mound-city of "
    "mechanical termites, explosions blooming across the dark hive slopes, "
    "year 2050 technology. " + NO_TEXT,

    # --- close-ups of a single hybrid machine ---
    STYLE + "Portrait-style close-up of a single battle-scarred grasshopper "
    "war machine standing alone in drifting smoke: dented chrome armor, "
    "one antenna sheared off — and grafted where its forelimbs meet the "
    "thorax, a pair of anatomically perfect human hands, fingers slowly "
    "flexing, wormy cable bundles pulsing under its jaw like tendons. "
    + NO_TEXT,

    STYLE + "Tight close-up of a wounded beetle machine dragging itself "
    "from a crater at dawn: half its face-plate torn away to reveal a "
    "realistic human face beneath, eyes open and calm, machined mandibles "
    "still working around it, oily worm-like tubes trailing from its "
    "cracked abdomen into the mud, hallucinatory biomechanical detail. "
    + NO_TEXT,

    STYLE + "Studio-sharp close-up of a lone assassin-bug machine perched "
    "on a heap of spent shell casings: its raised piercing proboscis is a "
    "gleaming surgical needle, its folded forelegs end in small human "
    "thumbs, and along its polished thorax a row of tiny human ears lies "
    "flush with the metal, magnified microscopic surface texture. " + NO_TEXT,

    # --- collapsed hive interiors ---
    STYLE + "Interior of a collapsed hive-fortress: shafts of dusty light "
    "falling through a caved-in ceiling of interlocked beetle-shell armor, "
    "broken hexagonal galleries stretching into darkness, dead mechanical "
    "workers hanging from the walls, a rescue column of ant machines "
    "tunneling through the rubble with glowing cutting jaws. " + NO_TEXT,

    STYLE + "Deep inside a ruined termite-mound city: a vast interior "
    "cavern where the queen machine lies toppled — a house-sized wormlike "
    "abdomen of segmented chrome, split open and spilling rows of unborn "
    "larva machines, among them pale anatomically human limbs tangled in "
    "the machinery, worker machines swarming over the wreck in the gloom. "
    + NO_TEXT,

    STYLE + "Claustrophobic tunnel shot inside a collapsed hive: the "
    "camera low in a crushed gallery as mechanical larvae worm through "
    "gaps in the fallen structure toward the lens, their wet-looking "
    "segmented bodies magnified and microscopic in texture, one dragging "
    "a severed chrome mantis arm, sparks dripping from ruptured conduits "
    "above. " + NO_TEXT,
]

GRADE = ("hue=s=0,curves=master='0/0.04 0.25/0.22 0.5/0.52 0.75/0.8 1/0.97',"
         "gblur=sigma=0.6,noise=alls=14:allf=t+u,"
         "vignette=PI/5.5:mode=backward:dither=1")


def generate(i, prompt):
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }).encode()
    req = urllib.request.Request(URL, data=body,
                                 headers={"Content-Type": "application/json"})
    raw = urllib.request.urlopen(req, timeout=180).read()
    resp_path = f"{OUT}/resp{i:02d}.json"
    with open(resp_path, "wb") as f:
        f.write(raw)
    resp = json.loads(raw)
    for part in resp["candidates"][0]["content"]["parts"]:
        inline = part.get("inlineData") or part.get("inline_data")
        if inline:
            png = f"{OUT}/insect_war_{i:02d}.png"
            with open(png, "wb") as f:
                f.write(base64.b64decode(inline["data"]))
            return png
    raise RuntimeError(f"no image part in resp{i:02d}.json")


def grade(png):
    out = png.replace(".png", "_bw.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", png,
                    "-vf", GRADE, out], check=True)
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    only = [int(a) for a in sys.argv[1:]]  # optional: retry specific indices
    for i, prompt in enumerate(PROMPTS, start=1):
        if only and i not in only:
            continue
        if not only and os.path.exists(f"{OUT}/insect_war_{i:02d}.png"):
            print(f"[{i:02d}] exists, skipping")
            continue
        try:
            png = generate(i, prompt)
            bw = grade(png)
            print(f"[{i:02d}] OK  {os.path.basename(png)}  {os.path.basename(bw)}")
        except Exception as e:
            print(f"[{i:02d}] FAIL {e}")


if __name__ == "__main__":
    main()
