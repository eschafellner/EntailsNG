"""Offline-PDF-Erzeugung mit echten Papiermaßen und begrenztem Speicherbedarf."""

import math
import tempfile
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

from configuration.translations import get_translation
from media_designer.models import MediaFont
from media_designer.schema import PAPER_MM, validate_elements


DPI = 300
SHEET_MARGIN_MM = 5
SHEET_GAP_MM = 4


def mm_to_px(value):
    return round(value * DPI / 25.4)


def sheet_layout(paper_size):
    """Ermittelt die Zahl unverkleinerter Karten auf A4 mit Schneideabstand."""
    width_mm, height_mm = PAPER_MM[paper_size]
    usable_width = PAPER_MM['A4'][0] - 2 * SHEET_MARGIN_MM
    usable_height = PAPER_MM['A4'][1] - 2 * SHEET_MARGIN_MM
    columns = math.floor((usable_width + SHEET_GAP_MM) / (width_mm + SHEET_GAP_MM))
    rows = math.floor((usable_height + SHEET_GAP_MM) / (height_mm + SHEET_GAP_MM))
    return columns, rows, columns * rows


def _base_card(template):
    if getattr(template, 'schema_version', 1) != 1:
        raise ValueError(get_translation('media_error_version', 'Unbekannte Vorlagenversion.'))
    validate_elements(template.elements, template.kind)
    width_mm, height_mm = PAPER_MM[template.paper_size]
    size = (mm_to_px(width_mm), mm_to_px(height_mm))
    card = Image.new('RGB', size, 'white')

    if template.background:
        with template.background.open('rb') as background_file:
            with Image.open(background_file) as source:
                background = ImageOps.exif_transpose(source).convert('RGB')
                card.paste(ImageOps.fit(background, size, method=Image.Resampling.LANCZOS))
    return card


def _load_fonts(template):
    font_ids = {element['font_id'] for element in template.elements if 'font_id' in element}
    fonts = {}
    for font in MediaFont.objects.filter(pk__in=font_ids):
        try:
            with font.file.open('rb') as font_file:
                fonts[font.pk] = font_file.read()
        except OSError as exc:
            raise ValueError(get_translation('media_error_font_unreadable', 'Eine Schriftdatei konnte nicht gelesen werden.')) from exc
    if set(fonts) != font_ids:
        raise ValueError(get_translation('media_error_font_missing', 'Eine ausgewählte Schriftart ist nicht mehr verfügbar.'))
    return fonts


def render_card(template, values, *, base_card=None, font_resources=None, font_cache=None):
    card = base_card.copy() if base_card is not None else _base_card(template)
    if font_resources is None:
        font_resources = _load_fonts(template)
    if font_cache is None:
        font_cache = {}
    size = card.size

    draw = ImageDraw.Draw(card)
    for index, element in enumerate(template.elements, 1):
        value = element.get('text', '') if element['source'] == 'static' else values.get(element['source'], '')
        text = str(value or '').strip()
        if not text:
            continue
        left = round(element['x'] * size[0])
        top = round(element['y'] * size[1])
        available_width = round(element['width'] * size[0])
        font_size = mm_to_px(element['font_size_mm'])
        minimum_size = mm_to_px(1.5)
        while True:
            font_id = element.get('font_id')
            font_key = (font_id, font_size)
            if font_key not in font_cache:
                if len(font_cache) >= 32:
                    font_cache.clear()
                font_cache[font_key] = (
                    ImageFont.truetype(BytesIO(font_resources[font_id]), size=font_size)
                    if font_id else ImageFont.load_default(size=font_size)
                )
            font = font_cache[font_key]
            spacing = round(font_size * 0.2)
            bounds = draw.multiline_textbbox(
                (0, 0), text, font=font, spacing=spacing,
                align=element['align'],
            )
            text_width = bounds[2] - bounds[0]
            text_height = bounds[3] - bounds[1]
            if text_width <= available_width and top + text_height <= size[1]:
                break
            if font_size <= minimum_size:
                raise ValueError(get_translation('media_error_text_fit', 'Textfeld {index} passt nicht auf die Karte: {text}', index=index, text=text[:40]))
            font_size -= 1

        if element['align'] == 'center':
            left += (available_width - text_width) // 2
        elif element['align'] == 'right':
            left += available_width - text_width
        draw.multiline_text(
            (left - bounds[0], top - bounds[1]), text, font=font,
            fill=element['color'], spacing=spacing, align=element['align'],
        )
    return card


def _draw_cut_marks(draw, x, y, width, height):
    outer = mm_to_px(2)
    inner = mm_to_px(0.5)
    for edge_x in (x, x + width):
        direction = -1 if edge_x == x else 1
        for edge_y in (y, y + height):
            vertical = -1 if edge_y == y else 1
            draw.line((edge_x + direction * inner, edge_y,
                       edge_x + direction * outer, edge_y), fill='#444444', width=2)
            draw.line((edge_x, edge_y + vertical * inner,
                       edge_x, edge_y + vertical * outer), fill='#444444', width=2)


def _render_sheet(template, values_rows, base_card, font_resources, font_cache):
    columns, rows, capacity = sheet_layout(template.paper_size)
    if capacity < 1:
        raise ValueError(get_translation('media_error_sheet_fit', 'Dieses Format passt nicht auf ein A4-Blatt.'))
    sheet = Image.new('RGB', (mm_to_px(210), mm_to_px(297)), 'white')
    draw = ImageDraw.Draw(sheet)
    card_width_mm, card_height_mm = PAPER_MM[template.paper_size]
    grid_width_mm = columns * card_width_mm + (columns - 1) * SHEET_GAP_MM
    grid_height_mm = rows * card_height_mm + (rows - 1) * SHEET_GAP_MM
    origin_x_mm = (210 - grid_width_mm) / 2
    origin_y_mm = (297 - grid_height_mm) / 2

    for index, values in enumerate(values_rows):
        column, row = index % columns, index // columns
        x = mm_to_px(origin_x_mm + column * (card_width_mm + SHEET_GAP_MM))
        y = mm_to_px(origin_y_mm + row * (card_height_mm + SHEET_GAP_MM))
        card = render_card(template, values, base_card=base_card,
                           font_resources=font_resources, font_cache=font_cache)
        sheet.paste(card, (x, y))
        _draw_cut_marks(draw, x, y, card.width, card.height)
        card.close()
    return sheet


def _write_pdf_page(output, offsets, page, index):
    """Schreibt ein JPEG-basiertes PDF-Blatt, ohne das bisherige PDF neu einzulesen."""
    image_id = 3 + index * 3
    content_id = image_id + 1
    page_id = image_id + 2
    jpeg = BytesIO()
    # Wie beim bisherigen Pillow-PDF-Export die Standard-JPEG-Komprimierung nutzen.
    page.save(jpeg, format='JPEG')
    image_data = jpeg.getvalue()
    jpeg.close()

    def start_object(object_id):
        while len(offsets) <= object_id:
            offsets.append(None)
        offsets[object_id] = output.tell()
        output.write(f'{object_id} 0 obj\n'.encode('ascii'))

    start_object(image_id)
    output.write((
        f'<< /Type /XObject /Subtype /Image /Width {page.width} /Height {page.height} '
        f'/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode '
        f'/Length {len(image_data)} >>\nstream\n'
    ).encode('ascii'))
    output.write(image_data)
    output.write(b'\nendstream\nendobj\n')

    width_pt = page.width * 72.0 / DPI
    height_pt = page.height * 72.0 / DPI
    content = f'q {width_pt} 0 0 {height_pt} 0 0 cm /Im0 Do Q\n'.encode('ascii')
    start_object(content_id)
    output.write(f'<< /Length {len(content)} >>\nstream\n'.encode('ascii'))
    output.write(content)
    output.write(b'endstream\nendobj\n')

    start_object(page_id)
    output.write((
        f'<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 {width_pt} {height_pt} ] '
        f'/Resources << /XObject << /Im0 {image_id} 0 R >> >> '
        f'/Contents {content_id} 0 R >>\nendobj\n'
    ).encode('ascii'))
    return page_id


def _finish_pdf(output, offsets, page_ids):
    offsets[1] = output.tell()
    output.write(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    offsets[2] = output.tell()
    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    output.write(f'2 0 obj\n<< /Type /Pages /Kids [ {kids} ] /Count {len(page_ids)} >>\nendobj\n'.encode('ascii'))
    xref_start = output.tell()
    output.write(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode('ascii'))
    for offset in offsets[1:]:
        output.write(f'{offset:010d} 00000 n \n'.encode('ascii'))
    output.write(f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n'.encode('ascii'))


def render_pdf(template, values_rows, *, on_a4=False):
    """Gibt eine seekbare temporäre PDF-Datei zurück; der Aufrufer schließt sie."""
    if not values_rows:
        raise ValueError(get_translation('media_error_empty_selection', 'Bitte mindestens einen Empfänger auswählen.'))
    if on_a4 and template.kind != 'BADGE':
        raise ValueError(get_translation('media_error_sheet_badges', 'A4-Bogen sind nur für Badges verfügbar.'))

    output = tempfile.TemporaryFile(mode='w+b')
    base_card = None
    try:
        base_card = _base_card(template)
        font_resources = _load_fonts(template)
        font_cache = {}
        if on_a4:
            capacity = sheet_layout(template.paper_size)[2]
            pages = (
                _render_sheet(template, values_rows[start:start + capacity], base_card,
                              font_resources, font_cache)
                for start in range(0, len(values_rows), capacity)
            )
        else:
            pages = (
                render_card(template, values, base_card=base_card,
                            font_resources=font_resources, font_cache=font_cache)
                for values in values_rows
            )

        output.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        offsets = [0, None, None]
        page_ids = []
        for index, page in enumerate(pages):
            try:
                page_ids.append(_write_pdf_page(output, offsets, page, index))
            finally:
                page.close()
        _finish_pdf(output, offsets, page_ids)
        output.seek(0)
        return output
    except Exception:
        output.close()
        raise
    finally:
        if base_card is not None:
            base_card.close()
