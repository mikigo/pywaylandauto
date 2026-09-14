from pywaylandauto.monitors import layout_from_regions


def test_single():
    layout = layout_from_regions([(0, 0, 1920, 1080, 1.0)])
    assert layout["bbox"] == {"x": 0, "y": 0, "width": 1920, "height": 1080}


def test_dual():
    layout = layout_from_regions([(0, 0, 1920, 1080, 1.0), (1920, 0, 1920, 1080, 1.0)])
    assert layout["bbox"]["width"] == 3840
    assert len(layout["monitors"]) == 2


def test_empty():
    assert layout_from_regions([]) is None