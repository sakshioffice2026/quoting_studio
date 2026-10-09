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

MAX_SIDE = int(os.environ.get("MAX_SIDE", "768"))
CONTROL_SCALE = float(os.environ.get("CONTROL_SCALE", "1.0"))
CONTROL_GUIDANCE_END = float(os.environ.get("CONTROL_GUIDANCE_END", "0.95"))
GUIDANCE = float(os.environ.get("GUIDANCE", "5.0"))
COLOUR_MATCH = float(os.environ.get("COLOUR_MATCH", "0.7"))

PROMPT = (
    "RAW photo of a house with a newly installed window, frame sitting recessed in the wall opening, "
    "soft shadow inside the reveal, clean sealant line, glass with natural sky reflection, "
    "same lighting and colour as the surrounding wall, sharp focus, photorealistic, 8k, film grain"
)
NEGATIVE_PROMPT = (
    "cartoon, illustration, 3d render, cgi, painting, flat colours, sticker, pasted, cutout, floating, "
    "blurry, distorted frame, warped lines, extra windows, extra bars, changed window shape, "
    "oversaturated, glow, text, watermark, low quality, deformed"
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
    gray = cv2.GaussianBlur(gray, (0, 0), 1.2)
    median = float(np.median(gray))
    low = int(max(20, 0.66 * median))
    high = int(min(255, max(low + 40, 1.33 * median)))
    edges = cv2.Canny(gray, low, high)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
    edges = np.stack([edges] * 3, axis=-1)
    return Image.fromarray(edges)


def _match_colour(result_rgb, original_rgb, region_mask, amount):
    sel = region_mask > 127
    if int(sel.sum()) < 64 or amount <= 0.0:
        return result_rgb

    res = cv2.cvtColor(result_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    org = cv2.cvtColor(original_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)

    for c in range(3):
        r_mean = float(res[..., c][sel].mean())
        r_std = float(res[..., c][sel].std()) + 1e-6
        o_mean = float(org[..., c][sel].mean())
        o_std = float(org[..., c][sel].std()) + 1e-6
        ratio = float(np.clip(o_std / r_std, 0.7, 1.4))
        matched = (res[..., c] - r_mean) * ratio + o_mean
        res[..., c] = np.where(sel, res[..., c] * (1.0 - amount) + matched * amount, res[..., c])

    res = np.clip(res, 0, 255).astype(np.uint8)
    return cv2.cvtColor(res, cv2.COLOR_LAB2RGB)


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
        guidance_scale=GUIDANCE,
        controlnet_conditioning_scale=CONTROL_SCALE,
        control_guidance_end=CONTROL_GUIDANCE_END,
        generator=generator,
    ).images[0]

    result_np = np.array(result.convert("RGB"))
    work_np = np.array(work)
    result_np = _match_colour(result_np, work_np, np.array(mask), COLOUR_MATCH)
    result = Image.fromarray(result_np).resize((ow, oh), Image.LANCZOS)

    soft = np.array(mask_img.resize((ow, oh), Image.BILINEAR), dtype=np.float32)
    soft = cv2.GaussianBlur(soft, (0, 0), max(1.5, 0.004 * max(ow, oh)))
    soft_mask = Image.fromarray(np.clip(soft, 0, 255).astype(np.uint8))
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
