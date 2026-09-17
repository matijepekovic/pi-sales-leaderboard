"""Border-only cutting. Never uses OCR, text, equal thirds, or adjustable margins."""
import cv2
import numpy as np


def cut_forms(image):
    """Return original-pixel strips from each outer top border to the next one.

    Full page width preserves side notes. The final strip ends at the page edge.
    A contour's wide outer rectangle distinguishes these stacked forms from
    internal cells and portrait summary tables. Unrecognized layouts are skipped.
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 30), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(30, h // 40))))
    grid = cv2.morphologyEx(horizontal | vertical, cv2.MORPH_CLOSE,
                          np.ones((max(3, w // 280), max(3, w // 280)), np.uint8))
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < .65 * w or bh < .08 * h or not 1.6 <= bw / bh <= 6:
            continue
        # Require a closed, box-like outside, not a wide handwritten underline.
        if cv2.contourArea(contour) < bw * bh * .8:
            continue
        mask = np.zeros((bh, bw), np.uint8)
        shifted = contour - np.array([[[x, y]]])
        cv2.drawContours(mask, [shifted], -1, 255, cv2.FILLED)
        xs = np.where(mask.any(axis=0))[0]
        ys = mask[:, xs].argmax(axis=0) + y
        # Interpolate the top border across the existing page side margins.
        # Curved/skewed top borders are retained; do not rotate/rewrite the form.
        top = np.rint(np.interp(np.arange(w), xs + x, ys)).astype(int)
        boxes.append((y, bh, top))
    boxes.sort(key=lambda b: b[0])
    if any(a[0] + a[1] > b[0] + 3 for a, b in zip(boxes, boxes[1:])):
        raise ValueError('Overlapping form borders; page needs a clearer scan')
    for index, (_, _, top) in enumerate(boxes):
        bottom = boxes[index + 1][2] if index + 1 < len(boxes) else np.full(w, h)
        if np.any(bottom <= top):
            raise ValueError('Ambiguous form boundaries')
        y0, y1 = int(top.min()), int(bottom.max())
        crop = image[y0:y1].copy()
        rows = np.arange(y0, y1)[:, None]
        crop[(rows < top[None, :]) | (rows >= bottom[None, :])] = 255
        yield index + 1, crop
