import sys
sys.path.append('..')

import os

from settings import StableDiffusionSettings
from generation import *
from prompts import text_inputs, style_modifiers
from eden_utils import *

def generate_lora(text_input, outdir, 
    lora_path = None,
    seed = int(time.time()),
    init_image = None,
    prefix = "",
    suffix = ""):

    print(text_input)

    args = StableDiffusionSettings(
        lora_path = lora_path,
        lora_scale = 0.8,
        mode = "generate",
        W = 1024+512,
        H = 1024,
        steps = 40,
        guidance_scale = 8,
        upscale_f = 1.0,
        text_input = text_input,
        init_image = init_image,
        seed = seed,
        n_samples = 1,
    )
    
    name = f'{prefix}{args.text_input[:40]}_{args.seed}_{int(time.time())}{suffix}'

    name = name.replace("/", "_")
    generator = make_images(args)

    for i, img in enumerate(generator):
        frame = f'{name}_{i}.jpg'
        os.makedirs(outdir, exist_ok = True)
        img.save(os.path.join(outdir, frame), quality=95)

    # save settings
    settings_filename = f'{outdir}/{name}.json'
    save_settings(args, settings_filename)


if __name__ == "__main__":

    outdir = "results_lora_does"
    lora_path = "/data/xander/Projects/cog/GitHub_repos/cog-sdxl/lora_models/does/checkpoints/checkpoint-4000"
    
    for i in range(20):
        seed = int(time.time())
        seed_everything(seed)
        text_input = random.choice(text_inputs)
        generate_lora(text_input, outdir, lora_path, seed = seed)