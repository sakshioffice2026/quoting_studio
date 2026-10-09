import cv2
import gradio as gr
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionControlNetInpaintPipeline, UniPCMultistepScheduler
from PIL import Image

MAX_SIDE = 768
CONTROL_SCALE = 1.0
CONTROL_GUIDANCE_END = 0.95
GUIDANCE = 5.0
COLOUR_MATCH = 0.7

PROMPT = (
    "RAW photo of a house with a newly installed window, frame sitting recessed in the wall opening, "
    "soft shadow inside the reveal, clean sealant line, glass with natural sky reflection, "
    "same lighting and colour as the surrounding wall, sharp focus, photorealistic, 8k, film grain"
)
NEGATIVE = (
    "cartoon, illustration, 3d render, cgi, painting, flat colours, sticker, pasted, cutout, floating, "
    "blurry, distorted frame, warped lines, extra windows, extra bars, changed window shape, "
    "oversaturated, glow, text, watermark, low quality, deformed"
)


controlnet = ControlNetModel.from_pretrained(
    "lllyasviel/control_v11p_sd15_canny", torch_dtype=torch.float16
)
pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-inpainting",
    controlnet=controlnet,
    torch_dtype=torch.float16,
    safety_checker=None,
    requires_safety_checker=False,
)
pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
pipe.to("cuda")
pipe.enable_attention_slicing()


def _canny(image_rgb):
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (0, 0), 1.2)
    median = float(np.median(gray))
    low = int(max(20, 0.66 * median))
    high = int(min(255, max(low + 40, 1.33 * median)))
    edges = cv2.Canny(gray, low, high)
    edges = cv2.dilate(edges, np.ones((2, 2), np.uint8))
    return Image.fromarray(np.stack([edges] * 3, axis=-1))


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
    img = Image.open(image_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    w, h = img.size

    scale = min(1.0, MAX_SIDE / float(max(w, h)))
    nw = max(64, int(round(w * scale / 8.0)) * 8)
    nh = max(64, int(round(h * scale / 8.0)) * 8)
    img_r = img.resize((nw, nh), Image.LANCZOS)
    mask_r = mask.resize((nw, nh), Image.NEAREST).point(lambda p: 255 if p > 127 else 0)

    control = _canny(np.array(img_r))

    generator = torch.Generator("cpu").manual_seed(int(seed))
    out = pipe(
        prompt=PROMPT,
        negative_prompt=NEGATIVE,
        image=img_r,
        mask_image=mask_r,
        control_image=control,
        num_inference_steps=int(steps),
        strength=float(min(0.6, max(0.1, float(strength)))),
        guidance_scale=GUIDANCE,
        controlnet_conditioning_scale=CONTROL_SCALE,
        control_guidance_end=CONTROL_GUIDANCE_END,
        generator=generator,
    ).images[0]

    out_np = _match_colour(np.array(out.convert("RGB")), np.array(img_r), np.array(mask_r), COLOUR_MATCH)
    out = Image.fromarray(out_np).resize((w, h), Image.LANCZOS)

    soft = np.array(mask.resize((w, h), Image.BILINEAR), dtype=np.float32)
    soft = cv2.GaussianBlur(soft, (0, 0), max(1.5, 0.004 * max(w, h)))
    soft_mask = Image.fromarray(np.clip(soft, 0, 255).astype(np.uint8))
    out = Image.composite(out, img, soft_mask)

    path = "/tmp/btl_enhanced.png"
    out.save(path)
    return path


demo = gr.Interface(
    fn=enhance,
    inputs=[
        gr.Image(type="filepath", label="composite"),
        gr.Image(type="filepath", label="mask"),
        gr.Slider(0.1, 0.6, value=0.35, label="strength"),
        gr.Slider(10, 40, value=20, step=1, label="steps"),
        gr.Number(value=7, label="seed"),
    ],
    outputs=gr.Image(type="filepath", label="result"),
    api_name="enhance",
)

demo.queue(max_size=3).launch(share=True)
