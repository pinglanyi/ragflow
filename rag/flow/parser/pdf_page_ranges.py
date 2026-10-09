"""Validate 1-based inclusive UI ranges and intersect worker page bounds."""


def pdf_page_ranges(pages, from_page=0, to_page=1000000):
    if type(from_page) is not int or type(to_page) is not int or from_page < 0 or to_page < from_page:
        raise ValueError("Invalid PDF worker page bounds")
    if pages is None or pages == []:
        return [(from_page, to_page)] if from_page < to_page else []
    if not isinstance(pages, list):
        raise ValueError("PDF pages must be a list of [from,to] ranges")  # noqa: TRY004
    ranges = []
    for pair in pages:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError("PDF pages must contain [from,to] pairs")
        start, end = pair
        if type(start) is not int or type(end) is not int or start < 1 or end < start:
            raise ValueError("PDF page ranges must be positive, ordered integers")
        start, end = max(start - 1, from_page), min(end, to_page)
        if start < end:
            ranges.append((start, end))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
