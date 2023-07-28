import os, time, random, sys, shutil, subprocess
sys.path.append('..')

if 0:
    os.environ["TORCH_HOME"] = "/src/.torch"
    os.environ["TRANSFORMERS_CACHE"] = "/src/.huggingface/"
    os.environ["DIFFUSERS_CACHE"] = "/src/.huggingface/"
    os.environ["HF_HOME"] = "/src/.huggingface/"
    os.environ["LPIPS_HOME"] = "/src/models/lpips/"

from settings import StableDiffusionSettings
from generation import *

def real2real(
    input_images, 
    outdir, 
    args = None, 
    seed = int(time.time()), 
    name_str = "",
    force_timepoints = None,
    save_video = True,
    remove_frames_dir = 0,
    save_phase_data = False,  # save condition vectors and scale for each frame (used for later upscaling)
    save_distance_data = 1,  # save distance plots to disk
    debug = 0):

    random.seed(seed)
    n = len(input_images)
    
    name = f"real2real_{name_str}_{seed}_{int(time.time()*100)}"
    frames_dir = os.path.join(outdir, name)
    os.makedirs(frames_dir, exist_ok=True)

    if args is None:
        args = StableDiffusionSettings(
            #watermark_path = "../assets/eden_logo.png",
            text_input = "real2real",  # text_input is also the title, but has no effect on interpolations
            interpolation_seeds = [random.randint(1, 1e8) for _ in range(n)],
            #interpolation_texts = ["photo of a group of people watching a volcano eruptting from the ground, amazing volcanic eruption, volcano eruption, active volcano, erupting volcano in distance, photorealistic",
            #                        "a woman with a pair of sunglasses and a snake head, cyberpunk medusa, snake woman hybrid, tristan eaton, jen bartel, beautiful octopus woman, hyperrealistic art nouveau, art nouveau! cyberpunk! style, art nouveau cyberpunk! style, cyberpunk art nouveau, medusa, portrait of teenage medusa, intricate artwork. neon eyes, beeple and jeremiah ketner"],
            interpolation_init_images = input_images,
            interpolation_init_images_use_img2txt = True,
            interpolation_init_images_power = 2.0,
            interpolation_init_images_min_strength = 0.25,  # a higher value will make the video smoother, but allows less visual change / journey
            interpolation_init_images_max_strength = random.choice([0.85]),
            #interpolation_init_images_min_strength = 0.0,  # a higher value will make the video smoother, but allows less visual change / journey
            #interpolation_init_images_max_strength = random.choice([0.0]),
            latent_blending_skip_f = random.choice([[0.1, 0.7]]),
            compile_unet = False,
            guidance_scale = 7.5,
            n_anchor_imgs = 3,
            n_frames = 32*n,
            loop = True,
            smooth = True,
            n_film = 0,
            fps = 9,
            steps =  40,
            sampler = "euler",
            seed = seed,
            H = 1024,
            W = 1024,
            upscale_f = 1.0,
            clip_interrogator_mode = "fast",
            lora_path = None,
        )

    random.seed(int(time.time()))
    args.offset_1 = random.choice([-1, 0, 1])
    args.offset_2 = random.choice([-1, 0, 1])

    #args.offset_1 = -1
    #args.offset_2 = 0
    print("Offsets:", args.offset_1, args.offset_2)

    # always make sure these args are properly set:
    args.frames_dir = frames_dir
    args.save_distance_data = save_distance_data
    args.save_phase_data = save_phase_data

    if debug: # overwrite some args to make things go FAST
        args.W, args.H = 1024, 1024
        args.steps = 35
        args.n_frames = 42*n
        args.n_anchor_imgs = 3

    # Only needed when visualising the smoothing algorithm (debugging mode)
    if args.save_distances_to_dir:
        args.save_distances_to_dir = os.path.join(frames_dir, args.save_distances_to_dir)
        os.makedirs(args.save_distances_to_dir, exist_ok=True)
    
    start_time = time.time()
    timepoints = []

    # run the interpolation and save each frame
    frame_counter = 0
    for frame, t_raw in make_interpolation(args, force_timepoints=force_timepoints):
        frame.save(os.path.join(frames_dir, "frame_%018.14f_%05d.jpg"%(t_raw, frame_counter)), quality=95)
        timepoints.append(t_raw)
        frame_counter += 1

    # run FILM postprocessing (frame blending)
    if args.n_film > 0:
        if 0: # old way, run FILM inside main thread, causes gpu memory leak from TF
            from film import interpolate_FILM
            frames_dir = interpolate_FILM(frames_dir, args.n_film)
        else: # run FILM as a subprocess:
            frames_dir = os.path.abspath(frames_dir)
            command = ["python", os.path.join(str(SD_PATH), "eden/film.py"), "--frames_dir", frames_dir, "--times_to_interpolate", str(args.n_film)]
            print("running command:", ' '.join(command))
            result = subprocess.run(command, text=True, capture_output=True)
            print(result)
            print(result.stdout)
            frames_dir = os.path.join(frames_dir, "interpolated_frames")

        args.fps = args.fps * (args.n_film + 1)

    if save_video:
        # save video
        loop = (args.loop and len(args.interpolation_seeds) == 2)
        video_filename = f'{outdir}/{name}.mp4'
        write_video(frames_dir, video_filename, loop=loop, fps=args.fps)
    else:
        video_filename = None

    # save settings
    settings_filename = f'{outdir}/{name}.json'
    args.total_render_time = "%.1f seconds" %(time.time() - start_time)
    args.avg_render_time_per_frame = "%.1f seconds" %((time.time() - start_time) / frame_counter)
    save_settings(args, settings_filename)

    if remove_frames_dir:
        shutil.rmtree(os.path.dirname(frames_dir))
        frames_dir = None

    return video_filename, frames_dir, timepoints

    

if __name__ == "__main__":

    outdir = "results_real2real"

    init_imgs = [
        "https://minio.aws.abraham.fun/creations-stg/7f5971f24bc5c122aed6c1298484785b4d8c90bce41cc6bfc97ad29cc179c53f.jpg",
        "https://minio.aws.abraham.fun/creations-stg/445eebc944a2d44bb5e0337ed4198ebf54217c7c17729b245663cf5c4fea182c.jpg",
        "https://minio.aws.abraham.fun/creations-stg/049848c63707293cddc766b2cbd230d9cde71f5075e48e9e02c6da03566ddae7.jpg",
        ]

    init_imgs = [
        "../assets/01.jpg",
        "../assets/02.jpg",
    ]


    n = 2
    input_dir = "/home/xander/Projects/cog/stable-diffusion-dev/eden/xander/img2img_inits/random"
    init_imgs = [os.path.join(input_dir, f) for f in os.listdir(input_dir) if f.endswith(".jpg")]
    init_imgs = [
        "https://generations.krea.ai/images/3cd0b8a8-34e5-4647-9217-1dc03a886b6a.webp",
        "https://generations.krea.ai/images/928271c8-5a8e-4861-bd57-d1398e8d9e7a.webp",
        "https://generations.krea.ai/images/865142e2-8963-47fb-bbe9-fbe260271e00.webp"
    ]

    for i in range(20):
        seed = np.random.randint(0, 1000)
        seed = 0

        random.seed(seed)
        input_images = random.sample(init_imgs, n)

        if 0:
            real2real(input_images, outdir, seed = seed)
        else:
            try:
                real2real(input_images, outdir, seed = seed)
            except KeyboardInterrupt:
                print("Interrupted by user")
                exit()  # or sys.exit()
            except Exception as e:
                print(f"Error: {e}")  # Optionally print the error
                continue