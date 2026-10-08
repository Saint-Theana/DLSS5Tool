"""Standalone PNG alpha, without a GPU or real model."""
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
import cv2
import numpy as np
import pytest
from dlss5tool.image_alpha import read_still, inference_color, resize_alpha, restore_alpha, checkerboard, resize_preview
from dlss5tool.gui import App, _write_image_bgr


@pytest.mark.parametrize('dtype', [np.uint8, np.uint16])
def test_decode_keeps_straight_colors_and_alpha(dtype):
    pixels = np.array([[[0, 0, 0, 0], [10, 100, 220, 128], [90, 150, 250, 255]]], np.uint8)
    stored = pixels if dtype == np.uint8 else pixels.astype(dtype) * 257
    ok, encoded = cv2.imencode('.png', stored)
    assert ok
    with patch('dlss5tool.image_alpha.np.fromfile', return_value=encoded):
        bgr, alpha = read_still('memory.png')
    np.testing.assert_array_equal(bgr, pixels[..., :3])
    np.testing.assert_array_equal(alpha, pixels[..., 3])


def test_hidden_colors_do_not_contaminate_nearby_visible_edges():
    bgr = np.full((140, 12, 3), (255, 0, 255), np.uint8)
    bgr[:, :5] = (30, 80, 210)
    alpha = np.zeros((140, 12), np.uint8)
    alpha[:, :4] = 255
    alpha[:, 4] = 128
    filled = inference_color(bgr, alpha)
    np.testing.assert_array_equal(filled[:, :5], bgr[:, :5])
    np.testing.assert_array_equal(filled[:, 5], np.tile([30, 80, 210], (140, 1)))
    np.testing.assert_array_equal(filled[127], filled[128])
    np.testing.assert_array_equal(bgr[:, 5], np.tile([255, 0, 255], (140, 1)))


def test_fully_transparent_image_is_finite_and_stays_transparent():
    bgr = np.zeros((4, 8, 3), np.uint8)
    alpha = np.zeros((4, 8), np.uint8)
    filled = inference_color(bgr, alpha)
    assert np.all(filled == 127)
    assert not restore_alpha(filled, alpha)[..., 3].any()


def test_checkerboard_does_not_change_export_pixels():
    bgr = np.full((24, 24, 3), (20, 100, 220), np.uint8)
    alpha = np.zeros((24, 24), np.uint8)
    alpha[:, 12:] = 255
    shown = checkerboard(bgr, alpha)
    assert shown[0, 0, 0] != shown[12, 0, 0]
    np.testing.assert_array_equal(shown[:, 12:], bgr[:, 12:])
    np.testing.assert_array_equal(restore_alpha(bgr, alpha)[..., :3], bgr)


def test_alpha_resize_keeps_bounds_and_partial_opacity():
    alpha = np.array([[0, 128, 255]], np.uint8)
    assert resize_alpha(alpha, (3, 1)) is alpha
    enlarged = resize_alpha(alpha, (12, 4))
    assert enlarged.shape == (4, 12) and enlarged.dtype == np.uint8
    assert enlarged.min() == 0 and enlarged.max() == 255
    assert np.any((enlarged > 0) & (enlarged < 255))


def test_preview_resampling_ignores_hidden_colors():
    color = np.array([[[0, 0, 255], [255, 0, 0]]], np.uint8)
    alpha = np.array([[255, 0]], np.uint8)
    shown = resize_preview(color, alpha, (1, 1), cv2.INTER_AREA)
    np.testing.assert_array_equal(shown, checkerboard(np.array([[[0, 0, 255]]], np.uint8),
                                                     np.array([[128]], np.uint8)))


@pytest.mark.parametrize('scale', [1, 2])
@pytest.mark.parametrize('view', [0, 1, 2])
def test_production_export_preserves_alpha_in_queue_request(tmp_path, scale, view):
    pixels = np.zeros((8, 12, 4), np.uint8)
    pixels[..., :3] = (40, 110, 220)
    pixels[:, 3:7, 3] = 128
    pixels[:, 7:, 3] = 255
    source, output = tmp_path/'transparent.png', tmp_path/'result.png'
    _write_image_bgr(str(source), pixels)
    app = App.__new__(App)
    app._collect_settings = lambda: {'output_view': view, 'output_mix': .5}
    app._ensure_shared_cache_pool = lambda: SimpleNamespace(name='test')
    app._super_resolution_scale = lambda settings: scale
    app._confirm_super_resolution_export = lambda *args, **kwargs: True
    app._process_still_image = lambda bgr, settings: cv2.resize(bgr, (12*scale, 8*scale))
    app._preview_composition_source = lambda frame, orig, processed: cv2.resize(orig, (12*scale, 8*scale))
    app._export_t0 = time.perf_counter()
    for name in ('_begin_export_ui', '_end_export_ui', '_remember_export', 'logln', 'set_progress'):
        setattr(app, name, Mock())
    result = app._export_image_source(str(source), {}, str(output), notify=False)
    assert result['success'], result
    decoded = cv2.imdecode(np.fromfile(output, np.uint8), cv2.IMREAD_UNCHANGED)
    assert decoded.shape == (8*scale, 12*scale, 4)
    np.testing.assert_array_equal(decoded[..., 3], resize_alpha(pixels[..., 3], (12*scale, 8*scale)))


def test_unsupported_format_never_silently_flattens(tmp_path):
    with pytest.raises(ValueError):
        _write_image_bgr(str(tmp_path/'no.jpg'), np.zeros((2, 2, 4), np.uint8))
    assert not (tmp_path/'no.jpg').exists()


def test_viewport_shows_alpha_and_invalidates_with_mask_change():
    app = App.__new__(App)
    app._source_kind = 'image'
    app._preview_zoom = 1.
    app._preview_pan_x = app._preview_pan_y = .5
    source = np.full((24, 24, 3), 77, np.uint8)
    app._image_alpha = np.zeros((24, 24), np.uint8)
    image, _ = app._render_viewport_image(source, 24, 24)
    assert image[0, 0, 0] == 160 and image[12, 0, 0] == 192
    app._image_alpha = np.full((24, 24), 255, np.uint8)
    opaque, _ = app._render_viewport_image(source, 24, 24)
    np.testing.assert_array_equal(opaque, source)
