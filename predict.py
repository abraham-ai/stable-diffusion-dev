# don't push DEBUG_MODE = True to Replicate!
DEBUG_MODE = True

import os
import sys
import tempfile
import requests
from typing import Iterator, Optional
from dotenv import load_dotenv

load_dotenv()

os.environ["TORCH_HOME"] = "/src/.torch"
os.environ["TRANSFORMERS_CACHE"] = "/src/.huggingface/"
os.environ["DIFFUSERS_CACHE"] = "/src/.huggingface/"
os.environ["HF_HOME"] = "/src/.huggingface/"
os.environ["LPIPS_HOME"] = "/src/models/lpips/"

sys.path.extend([
    "./eden",
    "./lora",
    "./lora/lora_diffusion",
    "/clip-interrogator",
    "/frame-interpolation"
])

from settings import StableDiffusionSettings
import eden_utils
import film
from cog import BasePredictor, BaseModel, File, Input, Path

checkpoint_options = [
#    "runwayml:stable-diffusion-v1-5",
#    "dreamlike-art:dreamlike-photoreal-2.0",
#    "huemin:fxhash_009",
    "eden:eden-v1",
    "gordon-berger:gordon-berger-figurative",
]
checkpoint_default = "eden:eden-v1"


class CogOutput(BaseModel):
    file: Path
    name: Optional[str] = None
    thumbnail: Optional[Path] = None
    attributes: Optional[dict] = None
    progress: Optional[float] = None
    isFinal: bool = False


def download(url, folder, ext):
    filename = url.split('/')[-1]+ext
    filepath = folder / filename
    os.makedirs(folder, exist_ok=True)
    if filepath.exists():
        return filepath
    raw_file = requests.get(url, stream=True).raw
    with open(filepath, 'wb') as f:
        f.write(raw_file.read())
    return filepath



class Predictor(BasePredictor):

    GENERATOR_OUTPUT_TYPE = Path if DEBUG_MODE else CogOutput

    def setup(self):
        print("cog:setup")
        import generation
        import interpolator
        generation.CLIP_INTERROGATOR_MODEL_PATH = '/src/cache'
        interpolator.LPIPS_DIR = "/src/models/lpips/weights/v0.1/alex.pth"
        film.FILM_MODEL_PATH = "/src/models/film/film_net/Style/saved_model"

    def predict(
        self,
        
        # Universal args
        mode: str = Input(
            description="Mode", default="generate",
            choices=["generate", "remix", "interpolate", "real2real", "interrogate"]
        ),
        stream: bool = Input(
            description="yield individual results if True", default=False
        ),
        stream_every: int = Input(
            description="for mode generate, how many steps per update to stream (steam must be set to True)", 
            default=1, ge=1, le=25
        ),
        width: int = Input(
            description="Width", 
            ge=256, le=2048, default=768
        ),
        height: int = Input(
            description="Height", 
            ge=256, le=2048, default=768
        ),
        checkpoint: str = Input(
            description="Which Stable Diffusion checkpoint to use",
            choices=checkpoint_options,
            default=checkpoint_default
        ),
        lora: str = Input(
            description="(optional) URL of Lora finetuning",
            default=None
        ),
        lora_scale: float = Input(
            description="Lora scale (how much of the Lora finetuning to apply)",
            ge=0.0, le=1.2, default=0.8
        ),
        sampler: str = Input(
            description="Which sampler to use", 
            default="euler", 
            # choices=["ddim", "plms", "klms", "dpm2", "dpm2_ancestral", "heun", "euler", "euler_ancestral"]
            choices=["euler"]
        ),
        steps: int = Input(
            description="Diffusion steps", 
            ge=10, le=100, default=60
        ),
        guidance_scale: float = Input(
            description="Strength of text conditioning guidance", 
            ge=0, le=30, default=7.5
        ),
        upscale_f: float = Input(
            description="Upscaling resolution",
            ge=1, le=2, default=1
        ),

        # Init image and mask
        init_image_data: str = Input(
            description="Load initial image from file, url, or base64 string", 
            default=None
        ),
        init_image_strength: float = Input(
            description="Strength of initial image", 
            ge=0.0, le=1.0, default=0.0
        ),

        # Generate mode
        text_input: str = Input(
            description="Text input (mode==generate)",
        ),
        uc_text: str = Input(
            description="Negative text input (mode==all)",
            default="watermark, text, nude, naked, nsfw, poorly drawn face, ugly, tiling, out of frame, blurry, blurred, grainy, signature, cut off, draft"
        ),
        seed: int = Input(
            description="random seed (mode==generate)", 
            ge=0, le=1e10, default=13
        ),
        n_samples: int = Input(
            description="batch size (mode==generate)",
            ge=1, le=4, default=1
        ),

        # Interpolate mode
        n_frames: int = Input(
            description="Total number of frames (mode==interpolate)",
            ge=3, le=1000, default=60
        ),

        # Interpolate mode
        interpolation_texts: str = Input(
            description="Interpolation texts (mode==interpolate)",
            default=None
        ),
        interpolation_seeds: str = Input(
            description="Seeds for interpolated texts (mode==interpolate)",
            default=None
        ),
        interpolation_init_images: str = Input(
            description="Interpolation init images, file paths or urls (mode==interpolate)",
            default=None
        ),
        interpolation_init_images_power: float = Input(
            description="Power for interpolation_init_images prompts (mode==interpolate)",
            ge=0.5, le=5.0, default=3.0
        ),
        interpolation_init_images_min_strength: float = Input(
            description="Minimum init image strength for interpolation_init_images prompts (mode==interpolate)",
            ge=0, le=0.75, default=0.25
        ),
        interpolation_init_images_max_strength: float = Input(
            description="Maximum init image strength for interpolation_init_images prompts (mode==interpolate)",
            ge=0.5, le=1.0, default=0.95
        ),
        scale_modulation: float = Input(
            description="Scale modulation amplitude for interpolation (mode==interpolate)",
            ge=0.0, le=0.25, default=0.0
        ),
        loop: bool = Input(
            description="Loops (mode==interpolate)",
            default=True
        ),
        smooth: bool = Input(
            description="Smooth (mode==interpolate)",
            default=False
        ),
        n_film: int = Input(
            description="Number of times to smooth final frames with FILM (default is 0) (mode==interpolate)",
            default=0, ge=0, le=2
        ),
        fps: int = Input(
            description="Frames per second (mode==interpolate)",
            default=12, ge=1, le=60
        ),

    ) -> Iterator[GENERATOR_OUTPUT_TYPE]:
    
        print("cog:predict:")
        import generation

        interpolation_texts = interpolation_texts.split('|') if interpolation_texts else None
        interpolation_seeds = [float(i) for i in interpolation_seeds.split('|')] if interpolation_seeds else None
        interpolation_init_images = interpolation_init_images.split('|') if interpolation_init_images else None
        
        lora_path = None
        if lora:
            lora_folder = Path('loras')
            lora_path = download(lora, lora_folder, '.safetensors')
        
        args = StableDiffusionSettings(
            ckpt = checkpoint,
            lora_path = str(lora_path) if lora_path else None,
            lora_scale = lora_scale,

            mode = mode,

            W = width - (width % 64),
            H = height - (height % 64),
            sampler = sampler,
            steps = steps,
            guidance_scale = guidance_scale,
            upscale_f = float(upscale_f),

            init_image_data = init_image_data,
            init_image_strength = init_image_strength,

            text_input = text_input,
            uc_text = uc_text,
            seed = seed,
            n_samples = n_samples,

            interpolation_texts = interpolation_texts,
            interpolation_seeds = interpolation_seeds,
            interpolation_init_images = interpolation_init_images,
            interpolation_init_images_power = interpolation_init_images_power,
            interpolation_init_images_min_strength = interpolation_init_images_min_strength,
            interpolation_init_images_max_strength = interpolation_init_images_max_strength,

            n_frames = n_frames,
            scale_modulation = scale_modulation,
            loop = loop,
            smooth = smooth,
            n_film = n_film,
            fps = fps,

            aesthetic_target = None, # None means we'll use the init_images as target
            aesthetic_steps = 10,
            aesthetic_lr = 0.0001,
            ag_L2_normalization_constant = 0.25, # for real2real, only 
        )

        print(args)

        out_dir = Path(tempfile.mkdtemp())

        if mode == "interrogate":
            interrogation = generation.interrogate(args)
            out_path = out_dir / f"interrogation.txt"
            with open(out_path, 'w') as f:
                f.write(interrogation)
            attributes = {'interrogation': interrogation}
            if DEBUG_MODE:
                yield out_path
            else:
                yield CogOutput(file=out_path, name=interrogation, thumbnail=None, attributes=attributes, isFinal=True, progress=1.0)

        elif mode == "generate" or mode == "remix":
            frames = generation.make_images(args)
            frame = frames[0]  # just one frame for now

            attributes = None
            if mode == "remix":
                attributes = {"interrogation": args.text_input}

            name = args.text_input
            out_path = out_dir / f"frame.jpg"
            frame.save(out_path, format='JPEG', subsampling=0, quality=95)
            
            if DEBUG_MODE:
                yield out_path
            else:
                yield CogOutput(file=out_path, name=name, thumbnail=out_path, attributes=attributes, isFinal=True, progress=1.0)

        else:
            
            if mode == "interpolate":
                generator = generation.make_interpolation(args)

            elif mode == "real2real":
                args.interpolation_init_images_use_img2txt = True
                generator = generation.make_interpolation(args)

            attributes = None
            thumbnail = None

            # generate frames
            for f, (frame, t_raw) in enumerate(generator):
                out_path = out_dir / ("frame_%0.16f.jpg" % t_raw)
                frame.save(out_path, format='JPEG', subsampling=0, quality=95)
                progress = f / args.n_frames
                if not thumbnail:
                    thumbnail = out_path
                if stream and f % stream_every == 0:
                    if DEBUG_MODE:
                        yield out_path
                    else:
                        yield CogOutput(file=out_path, thumbnail=None, attributes=attributes, progress=progress)

            # run FILM
            if args.n_film > 0:
                film.interpolate_FILM(str(out_dir), n_film)
                out_dir = out_dir / "interpolated_frames"

            # save video
            loop = (args.loop and len(args.interpolation_seeds) == 2)
            out_path = out_dir / "out.mp4"
            eden_utils.write_video(out_dir, str(out_path), loop=loop, fps=args.fps)

            if mode == "real2real":
                attributes = {"interrogation": args.interpolation_texts}

            name = " => ".join(args.interpolation_texts)

            if DEBUG_MODE:
                yield out_path
            else:
                yield CogOutput(file=out_path, name=name, thumbnail=thumbnail, attributes=attributes, isFinal=True, progress=1.0)
    