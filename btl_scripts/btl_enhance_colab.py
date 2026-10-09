import cv2
import gradio as gr
import numpy as np
import torch
from diffusers import ControlNetModel, StableDiffusionControlNetInpaintPipeline, UniPCMultistepScheduler
from PIL import Image

MAX_SIDE = 768

PROMPT = (
    "photo of a house with a new dark grey double glazed window recessed in the brick wall, "
    "shadow inside the reveal, glass reflecting blue sky, natural daylight, sharp, photorealistic"
)
NEGATIVE = (
    "cartoon, illustration, 3d render, cgi, flat colours, sticker, pasted, cutout, floating, "
    "blurry, deformed, extra bars, changed window shape, oversaturated, text, watermark"
)


controlnet = ControlNetModel.from_pretrained(
    "lllyasviel/control_v11p_sd15_canny", torch_dtype=torch.float16
)
pipe = StableDiffusionControlNetInpaintPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    controlnet=controlnet,
    torch_dtype=torch.float16,
    safety_checker=None,
)
pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
pipe.to("cuda")
pipe.enable_attention_slicing()


def enhance(image_path, mask_path, strength, steps, seed):
    img = Image.open(image_path).convert("RGB")
    mask = Image.open(mask_path).convert("L")
    w, h = img.size

    scale = MAX_SIDE / float(max(w, h))
    nw = max(64, int(w * scale) // 8 * 8)
    nh = max(64, int(h * scale) // 8 * 8)
    img_r = img.resize((nw, nh), Image.LANCZOS)
    mask_r = mask.resize((nw, nh), Image.NEAREST)

    edges = cv2.Canny(np.array(img_r), 100, 200)
    control = Image.fromarray(np.stack([edges] * 3, axis=-1))

    generator = torch.Generator("cuda").manual_seed(int(seed))
    out = pipe(
        prompt=PROMPT,
        negative_prompt=NEGATIVE,
        image=img_r,
        mask_image=mask_r,
        control_image=control,
        num_inference_steps=int(steps),
        strength=float(strength),
        guidance_scale=7.5,
        controlnet_conditioning_scale=0.9,
        generator=generator,
    ).images[0]

    out = out.resize((w, h), Image.LANCZOS)
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
