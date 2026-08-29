"""生成 ncmp 应用图标（assets/ncmp.ico）。

纯标准库实现：手工构造 ICO 文件（红底圆角方块 + 白色音符）。
仅在打包 exe 前运行一次：python assets/make_icon.py
"""
import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "ncmp.ico")

SIZES = [16, 32, 48, 64, 128]

BG = (236, 65, 65)      # 网易红 #EC4141
FG = (255, 255, 255)


def _inside_rounded(x: float, y: float, n: int) -> bool:
    """判断像素点是否在圆角矩形（边角半径 0.24n）内。"""
    rc = 0.24 * n
    cx = min(max(x, rc), n - rc)
    cy = min(max(y, rc), n - rc)
    return (x - cx) ** 2 + (y - cy) ** 2 <= rc * rc


def _inside_note(x: float, y: float, n: int) -> bool:
    """判断像素点是否在白色音符内：音符头(圆) + 符杆(竖条) + 符尾(矩形)。"""
    # 音符头：圆心 (0.36n, 0.66n)，半径 0.15n
    hx, hy, hr = 0.36 * n, 0.66 * n, 0.15 * n
    if (x - hx) ** 2 + (y - hy) ** 2 <= hr * hr:
        return True
    # 符杆：x∈[0.48n,0.56n]，y∈[0.26n,0.66n]
    if 0.48 * n <= x <= 0.56 * n and 0.26 * n <= y <= 0.66 * n:
        return True
    # 符尾：x∈[0.56n,0.76n]，y∈[0.26n,0.44n]
    if 0.56 * n <= x <= 0.76 * n and 0.26 * n <= y <= 0.44 * n:
        return True
    return False


def _make_image(n: int) -> bytes:
    """生成单个尺寸的 32bpp ICO 图像数据（BITMAPINFOHEADER + BGRA 像素 + AND 掩码）。"""
    # 40 字节 BITMAPINFOHEADER；biHeight = 2n（XOR + AND）
    bmih = struct.pack("<IiiHHIIiiII",
                       40, n, n * 2, 1, 32, 0, 4 * n * n, 0, 0, 0, 0)

    # BGRA 像素（自下而上）
    pixels = bytearray()
    for y in range(n - 1, -1, -1):
        for x in range(n):
            if not _inside_rounded(x + 0.5, y + 0.5, n):
                pixels += bytes((0, 0, 0, 0))
                continue
            color = FG if _inside_note(x + 0.5, y + 0.5, n) else BG
            pixels += bytes((color[2], color[1], color[0], 255))

    # AND 掩码：32bpp 带 Alpha，全 0
    stride = ((n + 31) // 32) * 4
    and_mask = bytes(stride * n)

    return bmih + bytes(pixels) + and_mask


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    images = []
    for n in SIZES:
        images.append((n, _make_image(n)))

    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    offset = 6 + 16 * len(images)
    for n, data in images:
        entries += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32,
                               len(data), offset)
        offset += len(data)

    with open(OUT, "wb") as f:
        f.write(header)
        f.write(entries)
        for _n, data in images:
            f.write(data)

    total = os.path.getsize(OUT)
    print(f"[OK] icon generated: {OUT} ({total} bytes, sizes={SIZES})")


if __name__ == "__main__":
    main()
