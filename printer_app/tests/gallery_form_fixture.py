"""Synthetic printed work-order form, with no customer data or OCR dependency."""
from printer_app.gallery.form_template import FormRegistration, TEMPLATE_FIELDS, map_box


NO_COLON = {'power_questions', 'fin_checklist', 'bid_sheets', 'pictures'}


def form_image(raster, scale=1.0):
    """Draw the full black grid and realistic text, including label punctuation."""
    cv2, np = raster
    image = np.full((round(809 * scale), round(1942 * scale)), 255, np.uint8)
    registration = FormRegistration(
        1.0, round(26 * scale), round(1916 * scale),
        round(19 * scale), round(787 * scale),
    )
    for field in TEMPLATE_FIELDS:
        left, top, right, bottom = map_box(registration, field.box)
        cv2.rectangle(image, (left, top), (right, bottom), 0, max(1, round(3 * scale)))
        left, top, right, bottom = map_box(registration, field.label_box)
        lines = ['Power', 'Questions'] if field.key == 'power_questions' else [
            field.label + ('' if field.key in NO_COLON else ':')
        ]
        line_height = (bottom - top) / len(lines)
        for index, text in enumerate(lines):
            (text_width, text_height), baseline = cv2.getTextSize(
                text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1,
            )
            font_scale = min(
                (right - left - 1) / text_width,
                (line_height - 1) / (text_height + baseline),
            )
            origin = (left, round(top + index * line_height + text_height * font_scale))
            cv2.putText(image, text, origin, cv2.FONT_HERSHEY_SIMPLEX,
                        font_scale, 0, 1, cv2.LINE_8)
    return image, registration
