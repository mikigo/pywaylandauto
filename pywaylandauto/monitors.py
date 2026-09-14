"""Monitor layout from EIS regions."""


def layout_from_regions(regions):
    if not regions:
        return None
    monitors = []
    bx = by = float("inf")
    bx2 = by2 = float("-inf")
    for i, (rx, ry, rw, rh, scale) in enumerate(regions):
        monitors.append({
            "x": int(rx), "y": int(ry),
            "width": int(rw), "height": int(rh),
            "scale": float(scale), "primary": i == 0,
        })
        bx = min(bx, rx)
        by = min(by, ry)
        bx2 = max(bx2, rx + rw)
        by2 = max(by2, ry + rh)
    return {
        "bbox": {"x": int(bx), "y": int(by),
                 "width": int(bx2 - bx), "height": int(by2 - by)},
        "monitors": monitors,
    }