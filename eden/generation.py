import os
import sys
from pathlib import Path

SD_PATH = Path(os.path.dirname(os.path.realpath(__file__))).parents[0]
ROOT_PATH = SD_PATH.parents[0]
CHECKPOINTS_PATH = os.path.join(SD_PATH, 'models/checkpoints')
CLIP_INTERROGATOR_MODEL_PATH = os.path.join(ROOT_PATH, 'cache')
LORA_PATH = os.path.join(ROOT_PATH, 'lora')
sys.path.append(LORA_PATH)

from _thread import start_new_thread
from queue import Queue
from copy import copy
import time
import numpy as np
import random
from PIL import Image
from einops import rearrange
import torch
import torchvision.transforms as T
import torchvision.transforms.functional as TF

import pipe as eden_pipe
from settings import _device
from eden_utils import *
from interpolator import *
from clip_tools import *
from planner import LatentTracker, create_init_latent, blend_inits
from diffusers import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline, StableDiffusionDepth2ImgPipeline

print("-----------------------------------------------------------------")
print("-----------------------------------------------------------------")
print("-----------------------sdxl branch!!-----------------------------")
print("-----------------------------------------------------------------")
print("-----------------------------------------------------------------")

def maybe_apply_watermark(args, x_images):
    # optionally, apply watermark to final image:
    if args.watermark_path is not None:
        # check if args.watermarker already exists:
        if not hasattr(args, 'watermarker'):
            # get width and height of image:
            pil_img = x_images[0]
            W, H = pil_img.size
            args.watermarker = WaterMarker(W, H, args.watermark_path) 
        # apply watermark:
        x_images = args.watermarker.apply_watermark(x_images)
    return x_images

@torch.no_grad()
def generate(
    args, 
    upscale = False,
    do_callback = False,
):
    assert args.text_input is not None

    seed_everything(args.seed)
    args.W = round_to_nearest_multiple(args.W, 64)
    args.H = round_to_nearest_multiple(args.H, 64)

    # Load init image
    if args.init_image_data:
        args.init_image = load_img(args.init_image_data, 'RGB')

    if args.init_image is not None:
        #args.W, args.H  = match_aspect_ratio(args.W * args.H, args.init_image)
        args.init_image = args.init_image.resize((args.W, args.H), Image.LANCZOS)

    # Load model
    global pipe
    pipe = eden_pipe.get_pipe(args)

    if args.interpolator is not None:
        args.interpolator.latent_tracker.create_new_denoising_trajectory(args, pipe)
    
    # adjust min n_steps:
    #n_steps = max(args.steps, int(args.min_steps/(1-args.init_image_strength)))
    #print(f"Adjusted n_steps from {args.steps} to {n_steps} to match min_steps {args.min_steps} and init_image_strength {args.init_image_strength}")

    # if init image strength == 1, just return the initial image
    if (args.init_image_strength == 1.0 or (int(args.steps*(1-args.init_image_strength)) < 1)) and args.init_image:
        latent = pil_img_to_latent(args.init_image, args, _device, pipe)
        if args.interpolator is not None:
            i,t=0,1
            args.interpolator.latent_tracker.add_latent(i, t, latent, init_image_strength = 1.0)

        pt_images = T.ToTensor()(args.init_image).unsqueeze(0).to(_device)
        pil_images = [args.init_image] * args.n_samples
        
        if args.upscale_f != 1.0:
            pt_images, pil_images = run_upscaler(args, pil_images)

        pil_images = maybe_apply_watermark(args, pil_images)
        return pt_images, pil_images

    if do_callback:
        callback_ = make_callback(
            latent_tracker = args.interpolator.latent_tracker if args.interpolator is not None else None,
        )
    else:
        callback_ = None

    generator = torch.Generator(device=_device).manual_seed(args.seed)
    
    if args.c is not None:
        assert args.uc is not None, "Must provide negative prompt conditioning if providing positive prompt conditioning"
        prompt, negative_prompt = None, None
    else:
        prompt, negative_prompt = args.text_input, args.uc_text
        args.c, args.uc = None, None

    if args.n_samples > 1: # Correctly handle batches:
        prompt = [prompt] * args.n_samples
        negative_prompt = [negative_prompt] * args.n_samples
        args.n_samples = 1

    if args.init_latent is not None:
        args.init_latent = args.init_latent.half()

    if 1:  # run img2img pipeline

        denoising_start = None
        if (args.init_image is None) and (args.init_latent is not None): # lerp
            print("Passing raw init_latent to img2img pipeline as image")
            args.init_image = args.init_latent

            if 1:
                denoising_start = 0.0  # ensures that args.init_image_strength is ignored and the full timestep trajectory is used (which is then clipped by start_timestep)
                # ---> add_noise = False

            else: # TODO, this should also work and maybe requires less/no modification to diffusers img2img pipe
                args.start_timestep = None
                denoising_start = args.init_image_strength


        elif (args.init_image is None) and (args.init_latent is None): # generate, no init_img
            print("Generating image from scratch using pure, random noise")
            shape = (1, pipe.unet.config.in_channels, args.H // pipe.vae_scale_factor, args.W // pipe.vae_scale_factor)
            args.init_image = torch.randn(shape, generator=generator, device=_device)
        elif (args.init_image is not None): # remix
            print("Passing init_image to img2img pipeline as image")

        pipe_output = pipe(
            prompt = prompt,
            negative_prompt = negative_prompt, 
            image = args.init_image, 
            strength = 1-args.init_image_strength, 
            denoising_start = denoising_start,
            start_timestep = args.start_timestep,
            num_inference_steps = args.steps,
            guidance_scale = args.guidance_scale,
            num_images_per_prompt = args.n_samples,
            prompt_embeds = args.c,
            negative_prompt_embeds = args.uc,
            pooled_prompt_embeds = args.pc,
            negative_pooled_prompt_embeds= args.puc,
            generator = generator,
            #latents = args.init_latent, # latents is implemented but not actually used in diffusers img2img pipe...
            callback = callback_,
        )
    else: # run txt2img pipeline
        pipe_output = pipe(
            prompt = prompt,
            negative_prompt = negative_prompt, 
            width = args.W, 
            height = args.H,
            num_inference_steps = args.steps,
            guidance_scale = args.guidance_scale,
            num_images_per_prompt = args.n_samples,
            prompt_embeds = args.c,
            negative_prompt_embeds = args.uc,
            pooled_prompt_embeds = args.pc,
            negative_pooled_prompt_embeds= args.puc,
            generator = generator,
            start_timestep = args.start_timestep,
            latents = args.init_latent,
            callback = callback_,
        )


    pil_images = pipe_output.images
    pt_images = [None]*len(pil_images)

    if args.upscale_f != 1.0:
        print(f"Upscaling with f = {args.upscale_f:.3f}...")
        pt_images, pil_images = run_upscaler(args, pil_images)

    pil_images = maybe_apply_watermark(args, pil_images)

    if args.c is None or args.uc is None:
        try:
            prompt_embeds = pipe._encode_prompt(
                    prompt,
                    _device,
                    args.n_samples,
                    args.guidance_scale > 1.0,
                    negative_prompt,
                )
        except:
            (
                prompt_embeds,
                negative_prompt_embeds,
                pooled_prompt_embeds,
                negative_pooled_prompt_embeds,
            ) = pipe.encode_prompt(
                prompt,
                _device,
                args.n_samples,
                args.guidance_scale > 1.0,
                negative_prompt)
            
            prompt_embeds_dict = {}
            prompt_embeds_dict['prompt_embeds'] = torch.cat([negative_prompt_embeds, prompt_embeds], dim=0)
            prompt_embeds_dict['pooled_prompt_embeds'] = torch.cat([negative_pooled_prompt_embeds, pooled_prompt_embeds], dim=0)
            prompt_embeds = prompt_embeds_dict
    else:
        prompt_embeds = torch.cat([args.uc, args.c])

    return prompt_embeds, pil_images


@torch.no_grad()
def make_interpolation(args, force_timepoints = None):
    #print_gpu_info(args, "start of make_interpolation()")
    
    # Always disbale upscaling for videos (since it introduces frame jitter)
    args.upscale_f = 1.0

    if args.interpolation_init_images and all(args.interpolation_init_images):
        if not args.interpolation_texts: #len(args.interpolation_texts) == 0:
            args.interpolation_texts = [None]*len(args.interpolation_init_images)

    if not args.interpolation_init_images:
        args.interpolation_init_images = [None]
        if args.interpolation_texts:
            args.interpolation_init_images = args.interpolation_init_images * len(args.interpolation_texts)
    if not args.interpolation_seeds:
        args.interpolation_seeds = [args.seed]
        args.n_frames = 1

    assert args.n_samples==1, "Batch size >1 not implemented for interpolation!"
    assert len(args.interpolation_texts) == len(args.interpolation_seeds), "Number of interpolation texts does not match number of interpolation seeds"
    assert len(args.interpolation_texts) == len(args.interpolation_init_images), "Number of interpolation texts does not match number of interpolation init images"
    assert len(args.interpolation_init_images) == len(args.interpolation_seeds), "Number of interpolation init images does not match number of interpolation seeds"

    if args.loop and len(args.interpolation_texts) > 2:
        args.interpolation_texts.append(args.interpolation_texts[0])
        args.interpolation_seeds.append(args.interpolation_seeds[0])
        args.interpolation_init_images.append(args.interpolation_init_images[0])

    # if there are init images, change width/height to their average
    interpolation_init_images = None
    if args.interpolation_init_images and all(args.interpolation_init_images):
        assert len(args.interpolation_init_images) == len(args.interpolation_texts), "Number of initial images must match number of prompts"
        
        args.use_init = True
        interpolation_init_images = get_uniformly_sized_crops(args.interpolation_init_images, args.H * args.W)
        args.W, args.H = interpolation_init_images[0].size

        if args.interpolation_init_images_use_img2txt:
            if args.interpolation_texts is None:
                args.interpolation_texts = [clip_interrogate(args.ckpt, init_img, args.clip_interrogator_mode, CLIP_INTERROGATOR_MODEL_PATH) for init_img in interpolation_init_images]
                print("Overwriting prompts with clip-interrogator results:", args.interpolation_texts)
            else: # get prompts for the images that dont have one:
                for jj, init_img in enumerate(interpolation_init_images):
                    if args.interpolation_texts[jj] is None:
                        init_img_prompt = clip_interrogate(args.ckpt, init_img, args.clip_interrogator_mode, CLIP_INTERROGATOR_MODEL_PATH)
                        print(f"Generated prompt for init_img_{jj}: {init_img_prompt}")
                        args.interpolation_texts[jj] = init_img_prompt

    else:
        args.use_init = False

    real2real = False if interpolation_init_images is None else True

    # Load model
    global pipe
    pipe = eden_pipe.get_pipe(args)

    # Release CLIP memory:
    del_clip_interrogator_models()

    args.interpolator = Interpolator(
        pipe, 
        args.interpolation_texts, 
        args.n_frames, 
        args, 
        _device, 
        smooth=args.smooth,
        seeds=args.interpolation_seeds,
        scales=[args.guidance_scale for _ in args.interpolation_texts],
        lora_paths=args.lora_paths,
    )

    n_frames = len(args.interpolator.ts)
    if force_timepoints is not None:
        n_frames = len(force_timepoints)

    active_lora_path = args.lora_paths[0] if args.lora_paths is not None else None

    ######################################

    for f in range(n_frames):
        force_t_raw = None
        if force_timepoints is not None:
            force_t_raw = force_timepoints[f]

        if 0: # catch errors and try to complete the video
            try:
                t, t_raw, prompt_embeds, init_latent, scale, return_index = args.interpolator.get_next_conditioning(verbose=0, save_distances_to_dir = args.save_distances_to_dir, t_raw = force_t_raw)
            except Exception as e:
                print("Error in interpolator.get_next_conditioning(): ", str(e))
                break
        else: # get full stack_trace, for debugging:
            t, t_raw, prompt_embeds, init_latent, scale, return_index = args.interpolator.get_next_conditioning(verbose=0, save_distances_to_dir = args.save_distances_to_dir, t_raw = force_t_raw)
        
        args.c, args.uc, args.pc, args.puc   = prompt_embeds
        args.guidance_scale = scale
        args.t_raw = t_raw

        if args.lora_paths is not None: # Maybe update the lora:
            if args.lora_paths[return_index] != active_lora_path:
                active_lora_path = args.lora_paths[return_index]
                print("Switching to lora path", active_lora_path)
                args.lora_path = active_lora_path


        #################################################################################################################################################################
        #################################################################################################################################################################
        #################################################################################################################################################################
        #################################################################################################################################################################


        if ((args.interpolation_init_images and all(args.interpolation_init_images) or len(args.interpolator.latent_tracker.frame_buffer.ts) >= args.n_anchor_imgs)):

            if not real2real: # lerping mode (no real init imgs, so use the generated keyframes)
                init_img1, init_img2 = args.interpolator.latent_tracker.frame_buffer.get_current_keyframe_imgs()
                init_img1, init_img2 = sample_to_pil(init_img1), sample_to_pil(init_img2)
            else: # real2real mode
                init_img1, init_img2 = interpolation_init_images[return_index], interpolation_init_images[return_index + 1]
            
            args.init_latent, args.init_image, args.init_image_strength, args.start_timestep = create_init_latent(args, t, init_img1, init_img2, _device, pipe, real2real = real2real)

        else: # anchor_frames for lerp: only use the raw init_latent noise from interpolator (using the input seeds)
            pipe.scheduler.set_timesteps(args.steps, device=_device)
            args.init_latent = init_latent * pipe.scheduler.init_noise_sigma
            args.init_image = None
            args.init_image_strength = 0.0
            args.start_timestep = None

        if args.planner is not None: # When audio modulation is active:
            args = args.planner.adjust_args(args, t_raw, force_timepoints=force_timepoints)

        print(f"Interpolating frame {f+1}/{len(args.interpolator.ts)} (t_raw = {t_raw:.5f},\
                init_strength: {args.init_image_strength:.2f},\
                latent skip_f: {args.interpolator.latent_tracker.latent_blending_skip_f:.2f},\
                splitting lpips_d: {args.interpolator.latent_tracker.frame_buffer.get_perceptual_distance_at_t(args.t_raw):.2f}),\
                keyframe {return_index+1}/{len(args.interpolation_texts) - 1}...")

        args.lora_path = active_lora_path
        _, pil_images = generate(args, do_callback = True)
        img_pil = pil_images[0]
        img_t = T.ToTensor()(img_pil).unsqueeze_(0).to(_device)
        args.interpolator.latent_tracker.add_frame(args, img_t, t, t_raw)

        yield img_pil, t_raw

    # Flush the final metadata to disk if needed:
    args.interpolator.latent_tracker.reset_buffer()
    #print_gpu_info(args, "end of make_interpolation()")

def make_images(args, enable_random_lr_flipping = True):
    if args.mode == "remix":

        if args.init_image_data:
            args.init_image = load_img(args.init_image_data, 'RGB')

        assert args.init_image is not None, "Must provide an init image in order to remix it!"
        
        if random.random() > 0.33 and enable_random_lr_flipping:
            args.init_image = args.init_image.transpose(Image.FLIP_LEFT_RIGHT)

        args.W, args.H = match_aspect_ratio(args.W * args.H, args.init_image)
        args.text_input = clip_interrogate(args.ckpt, args.init_image, args.clip_interrogator_mode, CLIP_INTERROGATOR_MODEL_PATH)

        del_clip_interrogator_models()

    assert args.text_input is not None, "No text input provided!"

    _, images_pil = generate(args)
    return images_pil


def make_callback(
    latent_tracker=None,
    extra_callback=None,
):
    def diffusers_callback(i, t, latents):
        if latent_tracker is not None:
            latent_tracker.add_latent(i, t, latents)
              
    return diffusers_callback

def run_upscaler(args_, imgs, 
        init_image_strength    = 0.68, 
        upscale_guidance_scale = 5.0,
        min_upscale_steps      = 16,  # never do less than this many steps
        max_n_pixels           = 1536**2, # max number of pixels to avoid OOM
    ):
    args = copy(args_)

    if args.c is not None:
        assert args.uc is not None, "Must provide negative prompt conditioning if providing positive prompt conditioning"
        args.uc_text, args.text_input = None, None
    else:
        args.c, args.uc = None, None

    #print_gpu_info(args, "start of run_upscaler()")
    args.W, args.H = args_.upscale_f * args_.W, args_.upscale_f * args_.H

    # set max_n_pixels to avoid OOM:
    if args.W * args.H > max_n_pixels:
        scale = math.sqrt(max_n_pixels / (args.W * args.H))
        args.W, args.H = int(scale * args.W), int(scale * args.H)

    args.W = round_to_nearest_multiple(args.W, 64)
    args.H = round_to_nearest_multiple(args.H, 64)

    x_samples_upscaled, x_images_upscaled = [], []

    # TODO: maybe clear our the existing pipe to avoid OOM?

    # Load the upscaling model:
    global upscaling_pipe
    # always upscale with SDXL-refiner by default:
    args.ckpt = "stabilityai/stable-diffusion-xl-refiner-0.9"
    upscaling_pipe = eden_pipe.get_upscaling_pipe(args)

    # Avoid doing too little steps when init_image_strength is very high:
    upscale_steps = int(max(args.steps * (1-init_image_strength), min_upscale_steps) / (1-init_image_strength))+1

    for i in range(len(imgs)): # upscale in a loop:
        args.init_image = imgs[i]
        image = upscaling_pipe(
            args.text_input,
            image=args.init_image.resize((args.W, args.H)),
            guidance_scale=upscale_guidance_scale,
            strength=1-init_image_strength,
            num_inference_steps=upscale_steps,
            negative_prompt=args.uc_text,
            prompt_embeds = args.c,
            negative_prompt_embeds = args.uc,

        ).images[0]
        x_samples_upscaled.extend([])
        x_images_upscaled.extend([image])

    #print_gpu_info(args, "end of run_upscaler()")

    return x_samples_upscaled, x_images_upscaled


def interrogate(args):
    if args.init_image_data:
        args.init_image = load_img(args.init_image_data, 'RGB')
    
    assert args.init_image is not None, "Must provide an init image"
    interrogated_prompt = clip_interrogate(args.ckpt, args.init_image, args.clip_interrogator_mode, CLIP_INTERROGATOR_MODEL_PATH)
    del_clip_interrogator_models()

    return interrogated_prompt