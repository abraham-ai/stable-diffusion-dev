import sys
sys.path.append('..')

import json
import os
import random
from PIL import Image
import moviepy.editor as mpy

from settings import StableDiffusionSettings
from generation import *
from prompts import *
from eden_utils import *


checkpoint_options = [
    "runwayml:stable-diffusion-v1-5",
    "dreamlike-art:dreamlike-photoreal-2.0",
    "eden:eden-v1"
]

#checkpoint_options = ["eden:eden-v1"]
checkpoint_options = ["stabilityai/stable-diffusion-xl-base-1.0"]

def generate_basic(
    text_input, 
    outdir, 
    steps_per_update = None, # None to disable intermediate frames
    text_input_2 = None,
    seed = int(time.time()),
    debug = False,
    init_image_data = None,
    prefix = "",
    suffix = ""):

    img_dir = "/data/xander/Projects/cog/eden-sd-pipelines/eden/xander/assets/controlnet_qr_best"
    #img_dir = "/data/xander/Projects/cog/stable-diffusion-dev/eden/xander/init_imgs/test"
    init_img = os.path.join(img_dir, random.sample(os.listdir(img_dir), 1)[0])

    args = StableDiffusionSettings(
        #ckpt = "/data/xander/Projects/cog/eden-sd-pipelines/models/checkpoints/eden:eden-v1",
        #ckpt = "runwayml:stable-diffusion-v1-5",
        mode = "generate",
        W = random.choice([1024, 1024+256, 1024+512]),
        H = random.choice([1024, 1024+256, 1024+512]),
        sampler = random.choice(["euler"]),
        steps = 50,
        guidance_scale = random.choice([6,8,10]),
        upscale_f = random.choice([1.0, 1.0]),
        text_input = text_input,
        text_input_2 = text_input_2,
        seed = seed,
        n_samples = 1,
        lora_path = None,
        init_image_data = init_img,
        #init_image_strength = random.choice([0.3, 0.35, 0.4, 0.45, 0.5]),
        #control_guidance_start = random.choice([0.0, 0.0, 0.05, 0.1]),
        #control_guidance_end = random.choice([0.5, 0.6, 0.7]),
        init_image_strength = random.choice([0.4, 0.5, 0.6, 0.7, 0.8]),
        control_guidance_end = random.choice([0.5, 0.6, 0.7]),
        #controlnet_path = random.choice(["controlnet-depth-sdxl-1.0-small","controlnet-canny-sdxl-1.0-small"]),
        #controlnet_path = "controlnet-monster-v2",
        controlnet_path = "/data/xander/Projects/cog/diffusers/examples/controlnet/luminance_controlnet_03_blurred/checkpoint-10000/controlnet",
        low_t = random.choice([75, 100, 125]),
        high_t = random.choice([150, 200, 250]),
    )

    controlnet_img = load_img(args.init_image_data, "RGB")

    #name = f'{prefix}{args.text_input[:40]}_{os.path.basename(args.lora_path)}_{args.seed}_{int(time.time())}{suffix}'
    name = f'{prefix}{args.text_input[:40]}_{args.seed}_{int(time.time())}{suffix}'
    name = name.replace("/", "_")
    
    generator = make_images(args)

    os.makedirs(outdir, exist_ok = True)
    save_control_img = True

    for i, img in enumerate(generator):
        frame = f'{name}_{i}.jpg'
        img.save(os.path.join(outdir, frame), quality=95)
        if save_control_img:
            control_frame = f'{name}_{i}_cond.jpg'
            controlnet_img.save(os.path.join(outdir, control_frame), quality=95)

    # save settings
    settings_filename = f'{outdir}/{name}.json'
    save_settings(args, settings_filename)


if __name__ == "__main__":

    
    outdir = "results_controlnet_qr_blurred_10000"

    
    for i in range(50):
        seed = random.randint(0, 100000)
        #seed = i
        
        seed_everything(seed)
        text_input = random.choice(sdxl_prompts)

        print(text_input)
        if 1:
            generate_basic(text_input, outdir, seed = seed)
        else:
            try:
                generate_basic(text_input, outdir, seed = seed)
            except KeyboardInterrupt:
                print("Interrupted by user")
                exit()  # or sys.exit()
            except Exception as e:
                print(f"Error: {e}")  # Optionally print the error
                continue