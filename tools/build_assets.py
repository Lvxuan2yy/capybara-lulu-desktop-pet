# -*- coding: utf-8 -*-
"""
水豚噜噜桌宠素材构建脚本
功能：把 assets/raw 下的白底立绘抠成透明 PNG，裁切空白并统一身高，输出到 assets/pet
算法：边缘泛洪填充找背景 -> 邻域扩散清理浅灰/渐变阴影 -> alpha 边缘羽化 -> bbox 裁切 -> 等比缩放
"""
import os
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "assets", "raw")
OUT = os.path.join(ROOT, "assets", "pet")

# 站立类统一输出高度（像素），睡姿较矮单独标定
# name: (输出高度, 是否水平翻转)
TARGETS = {
    "idle":  (320, False),
    "blink": (320, False),
    "drag":  (320, False),
    "happy": (320, False),
    "shy":   (320, False),
    "walk1": (320, False),
    "walk2": (320, False),
    "sleep": (210, False),
}

MARK = (255, 0, 255)  # 背景标记色（品红，角色身上不存在）


def _largest_component_mask(mask: np.ndarray, downscale: int = 8) -> np.ndarray:
    """在降采样图上做连通域分析，返回最大连通域（角色本体）对应的原尺寸 bool mask。"""
    h, w = mask.shape
    small = np.asarray(
        Image.fromarray(mask, "L").resize(
            (max(1, w // downscale), max(1, h // downscale)), Image.NEAREST))
    sh, sw = small.shape
    seen = np.zeros((sh, sw), dtype=bool)
    best = []
    for sy in range(sh):
        for sx in range(sw):
            if small[sy, sx] == 0 or seen[sy, sx]:
                continue
            stack = [(sy, sx)]
            seen[sy, sx] = True
            pts = []
            while stack:
                cy, cx = stack.pop()
                pts.append((cy, cx))
                y0, y1 = max(0, cy - 1), min(sh, cy + 2)
                x0, x1 = max(0, cx - 1), min(sw, cx + 2)
                block = small[y0:y1, x0:x1]
                for ny in range(y0, y1):
                    for nx in range(x0, x1):
                        if small[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            stack.append((ny, nx))
            if len(pts) > len(best):
                best = pts
    small_keep = np.zeros((sh, sw), dtype="uint8")
    for y, x in best:
        small_keep[y, x] = 255
    keep = np.asarray(
        Image.fromarray(small_keep, "L").resize((w, h), Image.NEAREST))
    return keep > 0


def remove_white_bg(img: Image.Image) -> Image.Image:
    img = img.convert("RGB")
    w, h = img.size
    work = img.copy()

    # 1) 从四边多个种子点泛洪，thresh 控制与白色的容许差
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
             (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]
    for x, y in seeds:
        ImageDraw.floodfill(work, (x, y), MARK, thresh=60)

    arr = np.asarray(work).astype(np.int16)

    # 2) 迭代扩散：低饱和度的亮色（白/浅灰/极淡暖色阴影），若邻接已标记背景则并入背景
    marked = (arr[:, :, 0] == 255) & (arr[:, :, 1] == 0) & (arr[:, :, 2] == 255)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    # 低饱和亮色 = 白底/浅灰；放宽到 min>=145、极差<=60 以吃掉暖灰投影
    # （角色主体为高饱和黄/橙，通道极差普遍 >80，不会被误除）
    bright_low_sat = (np.minimum(np.minimum(r, g), b) >= 145) & \
                     ((np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) <= 60)

    for _ in range(60):
        padded = np.pad(marked, 1, mode="constant", constant_values=True)
        neighbor = (padded[:-2, 1:-1] | padded[2:, 1:-1] |
                    padded[1:-1, :-2] | padded[1:-1, 2:] |
                    padded[:-2, :-2] | padded[:-2, 2:] |
                    padded[2:, :-2] | padded[2:, 2:])
        grow = bright_low_sat & neighbor & ~marked
        if not grow.any():
            break
        marked |= grow

    # 3) 逐列清扫脚下投影：每列最低的"角色像素"（高饱和黄橙 / 深色蹄子）
    #    以下出现的低饱和亮色一律视为投影；角色内部的眼白、牙齿位置更高，不受影响
    role = (((np.maximum(np.maximum(r, g), b) -
              np.minimum(np.minimum(r, g), b)) > 60) &
            (np.minimum(np.minimum(r, g), b) >= 90)) | \
           (np.minimum(np.minimum(r, g), b) < 120)
    shadow_like = (np.minimum(np.minimum(r, g), b) >= 118) & \
                  ((np.maximum(np.maximum(r, g), b) -
                    np.minimum(np.minimum(r, g), b)) <= 85)
    hh, ww = marked.shape
    row_idx = np.repeat(np.arange(hh)[:, None], ww, axis=1)
    role_rows = np.where(role, row_idx, -1)
    lowest_role = role_rows.max(axis=0)
    below = row_idx > (lowest_role[None, :] + 2)
    kill = shadow_like & below & (lowest_role[None, :] >= 0) & ~marked
    # 从已判定的投影像素向相邻同类像素扩散，吃掉延伸到身体轮廓之外的整条阴影
    for _ in range(80):
        padded = np.pad(kill, 1, mode="constant", constant_values=False)
        nb = (padded[:-2, 1:-1] | padded[2:, 1:-1] |
              padded[1:-1, :-2] | padded[1:-1, 2:] |
              padded[:-2, :-2] | padded[:-2, 2:] |
              padded[2:, :-2] | padded[2:, 2:])
        grow = shadow_like & nb & ~kill
        if not grow.any():
            break
        kill |= grow
    marked |= kill

    # 4) 连通域只保留最大块（角色本体），去掉所有孤立残渣
    mask = np.where(marked, 0, 255).astype("uint8")
    keep = _largest_component_mask(mask, downscale=4)
    mask_img = Image.fromarray(np.where(keep, mask, 0).astype("uint8"), "L")
    mask_img = mask_img.filter(ImageFilter.MinFilter(3))
    mask_img = mask_img.filter(ImageFilter.MaxFilter(3))

    # 5) 轻微羽化消除锯齿
    alpha_img = mask_img.filter(ImageFilter.GaussianBlur(0.7))

    rgba = img.convert("RGBA")
    rgba.putalpha(alpha_img)

    # 4) 按 alpha 裁切空白
    bbox = alpha_img.point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    return rgba


def post_clean_ground(img: Image.Image, ground_band: float = 0.74) -> Image.Image:
    """最终小图上的脚底投影清扫：底部条带内，角色实体以下的低饱和浅色像素透明化，
    再邻域扩散并只保留最大连通域。黄/橙角色（高饱和）与深色蹄子不受影响。"""
    a = np.asarray(img.convert("RGBA")).astype(np.int16)
    r, g, b, al = a[:, :, 0], a[:, :, 1], a[:, :, 2], a[:, :, 3]
    h, w = al.shape
    mn = np.minimum(np.minimum(r, g), b)
    sat = np.maximum(np.maximum(r, g), b) - mn
    solid = al > 80
    role = solid & ((sat > 88) | (mn < 108))
    shadowish = solid & (mn >= 108) & (sat <= 86)

    row_idx = np.repeat(np.arange(h)[:, None], w, axis=1)
    lowest = np.where(role, row_idx, -1).max(axis=0)
    band = row_idx >= int(h * ground_band)
    kill = shadowish & band & (row_idx > (lowest[None, :] + 1))
    for _ in range(40):
        padded = np.pad(kill, 1, mode="constant", constant_values=False)
        nb = (padded[:-2, 1:-1] | padded[2:, 1:-1] |
              padded[1:-1, :-2] | padded[1:-1, 2:] |
              padded[:-2, :-2] | padded[:-2, 2:] |
              padded[2:, :-2] | padded[2:, 2:])
        grow = shadowish & band & nb & ~kill
        if not grow.any():
            break
        kill |= grow

    al2 = np.where(kill, 0, al).astype("uint8")
    keep = _largest_component_mask((al2 > 60).astype("uint8") * 255, downscale=2)
    a[:, :, 3] = np.where(keep, al2, 0)
    return Image.fromarray(a.astype("uint8"), "RGBA")


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, (target_h, flip) in TARGETS.items():
        src = os.path.join(RAW, f"{name}_raw.png")
        img = Image.open(src)
        cut = remove_white_bg(img)
        if flip:
            cut = cut.transpose(Image.FLIP_LEFT_RIGHT)
        w, h = cut.size
        new_w = max(1, round(w * target_h / h))
        cut = cut.resize((new_w, target_h), Image.LANCZOS)
        cut = post_clean_ground(cut)
        cut.save(os.path.join(OUT, f"{name}.png"))
        print(f"{name:6s} -> {new_w} x {target_h}")
    print("done ->", OUT)


if __name__ == "__main__":
    main()
