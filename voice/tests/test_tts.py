import numpy as np
from mirror_voice.tts import to_int16


def test_to_int16_scales_and_clips():
    out = to_int16([0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0])
    assert out.dtype == np.int16
    assert list(out) == [0, 16383, -16383, 32767, -32767, 32767, -32767]
