import os
import tempfile

import cv2
import gradio as gr
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionControlNetInpaintPipeline, UniPCMultistepScheduler
from PIL import Image

INPAINT_MODEL = os.environ.get("INPAINT_MODEL", "stable-diffusion-v1-5/stable-diffusion-inpainting")
CONTROLNET_MODEL = os.environ.get("CONTROLNET_MODEL", "lllyasviel/control_v11p_sd15_canny")

MAX_SIDE = 768
CANNY_LOW = 100
CANNY_HIGH = 200
CONTROL_SCALE = 1.0

PROMPT = (
    "photo of a house exterior with a new modern window, realistic glass, "
    "natural daylight, sharp frame edges, high detail, photorealistic"
)
NEGATIVE_PROMPT = (
    "blurry, distorted frame, warped lines, extra windows, text, watermark, "
    "cartoon, painting, low quality, deformed"
)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

_pipe = None


def get_pipe():
    global _pipe
    if _pipe is not None:
        return _pipe

    controlnet = ControlNetModel.from_pretrained(CONTROLNET_MODEL, torch_dtype=DTYPE)
    pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
        INPAINT_MODEL,
        controlnet=controlnet,
        torch_dtype=DTYPE,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
    pipe.to(DEVICE)
    if DEVICE == "cuda":
        pipe.enable_attention_slicing()
    _pipe = pipe
    return _pipe


def _fit_size(w, h):
    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    nw = max(64, int(round(w * scale / 8.0)) * 8)
    nh = max(64, int(round(h * scale / 8.0)) * 8)
    return nw, nh


def _canny(image_rgb):
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, CANNY_LOW, CANNY_HIGH)
    edges = np.stack([edges] * 3, axis=-1)
    return Image.fromarray(edges)


def enhance(image_path, mask_path, strength, steps, seed):
    if not image_path or not mask_path:
        raise gr.Error("image and mask are required")

    strength = float(min(0.6, max(0.1, float(strength))))
    steps = int(min(40, max(8, int(steps))))
    seed = int(seed)

    original = Image.open(image_path).convert("RGB")
    mask_img = Image.open(mask_path).convert("L")
    ow, oh = original.size

    nw, nh = _fit_size(ow, oh)
    work = original.resize((nw, nh), Image.LANCZOS)
    mask = mask_img.resize((nw, nh), Image.NEAREST)
    mask = mask.point(lambda p: 255 if p > 127 else 0)

    control = _canny(np.array(work))

    pipe = get_pipe()
    generator = torch.Generator(device="cpu").manual_seed(seed)

    result = pipe(
        prompt=PROMPT,
        negative_prompt=NEGATIVE_PROMPT,
        image=work,
        mask_image=mask,
        control_image=control,
        strength=strength,
        num_inference_steps=steps,
        guidance_scale=6.5,
        controlnet_conditioning_scale=CONTROL_SCALE,
        generator=generator,
    ).images[0]

    result = result.resize((ow, oh), Image.LANCZOS)

    soft_mask = mask_img.resize((ow, oh), Image.BILINEAR)
    out = Image.composite(result, original, soft_mask)

    out_path = os.path.join(tempfile.mkdtemp(), "enhanced.png")
    out.save(out_path, format="PNG")
    return out_path


with gr.Blocks() as demo:
    gr.Markdown("Window enhance (SD inpaint + ControlNet canny)")
    with gr.Row():
        in_image = gr.Image(type="filepath", label="composite")
        in_mask = gr.Image(type="filepath", label="mask")
    with gr.Row():
        in_strength = gr.Slider(0.1, 0.6, value=0.35, step=0.01, label="strength")
        in_steps = gr.Slider(8, 40, value=20, step=1, label="steps")
        in_seed = gr.Number(value=7, precision=0, label="seed")
    run_btn = gr.Button("Enhance")
    out_image = gr.Image(type="filepath", label="result")

    run_btn.click(
        enhance,
        inputs=[in_image, in_mask, in_strength, in_steps, in_seed],
        outputs=out_image,
        api_name="enhance",
    )

demo.queue(max_size=4, default_concurrency_limit=1)

if __name__ == "__main__":
    demo.launch()
