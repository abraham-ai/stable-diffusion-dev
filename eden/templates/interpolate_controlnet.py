import os, random, sys, time, random
sys.path.append('..')

from settings import StableDiffusionSettings
from generation import *
from eden_utils import *
from prompts import *

def lerp(
    interpolation_texts, 
    outdir, 
    args = None, 
    seed = int(time.time()), 
    interpolation_seeds = None,
    name_str = "",
    save_phase_data = False,     # save condition vectors and scale for each frame (used for later upscaling)
    save_distance_data = False,  # save distance plots to disk
    debug = 1):

    seed_everything(seed)
    n = len(interpolation_texts)
    
    name = f"prompt2prompt_{int(time.time())}_seed_{seed}_{name_str}"
    frames_dir = os.path.join(outdir, name)
    os.makedirs(frames_dir, exist_ok=True)

    #control_image = "/data/xander/Projects/cog/eden-sd-pipelines/eden/xander/assets/people/chebel.jpg"

    img_dir = "/data/xander/Projects/cog/eden-sd-pipelines/eden/xander/assets/init_imgs/01_great_inits"
    init_image = random.choice(os.listdir(img_dir))
    init_image = os.path.join(img_dir, init_image)
    

    args = StableDiffusionSettings(
        ckpt = "juggernaut_XL2",
        text_input = interpolation_texts[0],
        interpolation_texts = interpolation_texts,
        interpolation_seeds = interpolation_seeds if interpolation_seeds else [random.randint(1, 1e8) for i in range(n)],
        n_frames = 48*n,
        guidance_scale = random.choice([8]),
        loop = True,
        smooth = True,
        latent_blending_skip_f = random.choice([[0.05, 0.65]]),
        n_anchor_imgs = random.choice([3]),
        n_film = 1,
        fps = 12,
        steps = 40,
        seed = seed,
        H = 1024+512,
        W = 1024,
        init_image = init_image,
        init_image_strength = random.choice([0.15,0.2,0.25]),
        #control_image = control_image,
        #control_image_strength = random.choice([0.45,0.55,0.65,0.75]),
        #controlnet_path = random.choice(["controlnet-canny-sdxl-1.0-small", "controlnet-luminance-sdxl-1.0"]),
    
    )

    # always make sure these args are properly set:
    args.frames_dir = frames_dir
    args.save_distance_data = save_distance_data
    args.save_phase_data = save_phase_data

    if debug: # overwrite some args to make things go FAST
        args.W, args.H = 640, 640
        args.steps = 20
        args.n_frames = 6*n
        args.init_image_strength = 0.3

    start_time = time.time()

    # run the interpolation and save each frame
    frame_counter = 0
    for frame, t_raw in make_interpolation(args):
        frame.save(os.path.join(frames_dir, "frame_%018.14f_%05d.jpg"%(t_raw, frame_counter)), quality=95)
        frame_counter += 1
        
    # run FILM
    if args.n_film > 0:
        # clear cuda cache:
        torch.cuda.empty_cache()

        print('predict.py: running FILM...')
        FILM_MODEL_PATH = os.path.join(SD_PATH, 'models/film/film_net/Style/saved_model')
        film_script_path = os.path.join(SD_PATH, 'eden/film.py')
        abs_out_dir_path = os.path.abspath(str(frames_dir))
        command = ["python", film_script_path, "--frames_dir", abs_out_dir_path, "--times_to_interpolate", str(args.n_film), '--update_film_model_path', FILM_MODEL_PATH]
        
        run_and_kill_cmd(command)
        print("predict.py: FILM done.")
        frames_dir = Path(os.path.join(abs_out_dir_path, "interpolated_frames"))

    # save video
    loop = (args.loop and len(args.interpolation_seeds) == 2)
    video_filename = f'{outdir}/{name}.mp4'
    write_video(frames_dir, video_filename, loop=loop, fps=args.fps)

    # save settings
    settings_filename = f'{outdir}/{name}.json'
    args.total_render_time = "%.1f seconds" %(time.time() - start_time)
    save_settings(args, settings_filename)


if __name__ == "__main__":

    outdir = "results_controlnet_video"
    n = 2

    for i in range(3):
        seed = np.random.randint(0, 1000)
        #seed = i
        
        seed_everything(seed)

        interpolation_texts = random.sample(text_inputs, n)

        for txt in interpolation_texts:
            print(txt)
            print("-----------------------")
        
        if 0:
            lerp(interpolation_texts, outdir, seed=seed, save_distance_data=True, interpolation_seeds=None)
        else:
            try:
                lerp(interpolation_texts, outdir, seed=seed, save_distance_data=True, interpolation_seeds=None)
            except KeyboardInterrupt:
                print("Interrupted by user")
                exit()  # or sys.exit()
            except Exception as e:
                print(f"Error: {e}")  # Optionally print the error
                continue